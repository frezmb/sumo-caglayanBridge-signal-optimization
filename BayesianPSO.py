# bo_optuna.py
# Bayesian Optimization (Optuna TPE) ile (gA,gB) arama.
# Ölçüm: pso.py --replay çıktısı metrics.json
# Güvenlik: sadece runs/05_... altında yazar.

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import optuna


@dataclass
class Metrics:
    meanWaitingTime: float
    co2_total_abs: float
    teleports: int
    ended: int


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_metrics(metrics_path: Path) -> Metrics:
    m = load_json(metrics_path)
    return Metrics(
        meanWaitingTime=float(m.get("meanWaitingTime", 1e9)),
        co2_total_abs=float(m.get("co2_total_abs", 1e18)),
        teleports=int(m.get("teleports", 10**9)),
        ended=int(m.get("ended", 0)),
    )


def safe_under_runs05(path: Path) -> None:
    # Sadece runs/05_ ile başlayan klasörler altına yazalım
    parts = [x.lower() for x in path.parts]
    if "runs" not in parts:
        raise RuntimeError(f"Güvenlik: çıktı runs altında değil: {path}")
    idx = parts.index("runs")
    if idx + 1 >= len(parts):
        raise RuntimeError(f"Güvenlik: runs altı boş: {path}")
    if not parts[idx + 1].startswith("05_"):
        raise RuntimeError(f"Güvenlik: sadece runs/05_... altında yazılır: {path}")


def run_replay(
    project_root: Path,
    out_dir: Path,
    seed: int,
    params_path: Path,
    baseline: str,
) -> Path:
    """
    pso.py --replay çalıştırır.
    Dönen değer: metrics.json path
    """
    safe_under_runs05(out_dir)

    # Temiz başlat (out_dir varsa sil)
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(project_root / "pso.py"),
        "--baseline", baseline,
        "--replay",
        "--params", str(params_path),
        "--seed", str(seed),
        "--out", str(out_dir),
    ]

    # Emoji vb. yazmayalım; encoding sorunlarına takılmayalım
    env = os.environ.copy()
    env["PYTHONUTF8"] = env.get("PYTHONUTF8", "1")
    env["PYTHONIOENCODING"] = env.get("PYTHONIOENCODING", "utf-8")

    # Çalıştır
    subprocess.run(cmd, cwd=str(project_root), check=True, env=env)

    # pso.py genelde kosu_001/metrics.json üretir
    metrics_path = out_dir / "kosu_001" / "metrics.json"
    if not metrics_path.exists():
        # bazı koşullarda kosu_xxx değişebilir diye tarayalım
        candidates = list(out_dir.glob("kosu_*/*metrics.json")) + list(out_dir.glob("kosu_*/metrics.json"))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"metrics.json bulunamadı: {out_dir}")

    return metrics_path


def compute_score(
    m: Metrics,
    base: Metrics,
    w_wait: float,
    w_co2: float,
    min_ended_ratio: float,
) -> float:
    # Sert kısıtlar
    if m.teleports != 0:
        return 5e8 + m.teleports * 1e6
    min_ok = int(min_ended_ratio * base.ended)
    if m.ended < min_ok:
        return 5e8 + (min_ok - m.ended) * 1e5

    wait_term = m.meanWaitingTime / max(1e-9, base.meanWaitingTime)
    co2_term = m.co2_total_abs / max(1e-9, base.co2_total_abs)
    return (w_wait * wait_term) + (w_co2 * co2_term)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", required=True, help="örn: --seeds 2 42")
    ap.add_argument("--baseline", type=str, default="kural", choices=["kural", "temel"], help="baz metrik kaynağı")
    ap.add_argument("--min-ended-ratio", type=float, default=0.95)
    ap.add_argument("--w-wait", type=float, default=0.85)
    ap.add_argument("--w-co2", type=float, default=0.15)

    ap.add_argument("--gmin", type=float, default=10.0)
    ap.add_argument("--gmax", type=float, default=90.0)

    ap.add_argument("--n-trials", type=int, default=60)
    ap.add_argument("--robust", type=str, default="worst", choices=["worst", "mean"], help="çok-seed birleştirme")
    ap.add_argument("--study-name", type=str, default="bo_gA_gB")

    ap.add_argument("--out-root", type=str, default="runs/05_bo_optuna")
    ap.add_argument("--tag", type=str, default="", help="çıktı etiket: örn ww85_wc15 gibi")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent
    out_root = (project_root / args.out_root).resolve()

    # runs/05_ ile başlamıyorsa düzelt (güvenlik)
    if out_root.parts[-1].startswith("05_") is False and "runs" in [p.lower() for p in out_root.parts]:
        # Kullanıcı runs/05_bo_optuna verdi; zaten 05_ başlıyor.
        pass

    # Baseline metrikleri: mevcut koşulmuş klasörlerden okuyacağız (daha hızlı ve deterministik)
    # kural -> runs/02_kural_seed{seed}/kosu_001/metrics.json
    # temel -> runs/01_temel_seed{seed}/kosu_001/metrics.json
    base_by_seed: dict[int, Metrics] = {}
    for s in args.seeds:
        if args.baseline == "kural":
            p = project_root / f"runs/02_kural_seed{s}/kosu_001/metrics.json"
        else:
            p = project_root / f"runs/01_temel_seed{s}/kosu_001/metrics.json"
        if not p.exists():
            raise FileNotFoundError(f"Baseline metrics yok: {p}")
        base_by_seed[s] = read_metrics(p)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = out_root / f"05_bo_{stamp}"  # runs/05_bo_optuna/05_bo_...
    safe_under_runs05(run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    # Optuna storage (resume için)
    storage_path = run_root / "study.db"
    storage = f"sqlite:///{storage_path.as_posix()}"

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(
        direction="minimize",
        study_name=args.study_name,
        sampler=sampler,
        storage=storage,
        load_if_exists=True,
    )

    def objective(trial: optuna.Trial) -> float:
        gA = trial.suggest_float("gA", args.gmin, args.gmax)
        gB = trial.suggest_float("gB", args.gmin, args.gmax)

        # Her trial için tek params dosyası (aynı gA,gB tüm seed’lere uygulanır)
        trial_dir = run_root / f"trial_{trial.number:04d}"
        safe_under_runs05(trial_dir)
        trial_dir.mkdir(parents=True, exist_ok=True)
        params_path = trial_dir / "params.json"
        save_json(params_path, {"gA": gA, "gB": gB})

        scores = []
        for s in args.seeds:
            seed_dir = trial_dir / f"seed_{s}"
            metrics_path = run_replay(
                project_root=project_root,
                out_dir=seed_dir,
                seed=s,
                params_path=params_path,
                baseline=args.baseline,
            )
            m = read_metrics(metrics_path)
            base = base_by_seed[s]
            sc = compute_score(m, base, args.w_wait, args.w_co2, args.min_ended_ratio)

            # log
            trial.set_user_attr(f"seed{s}_wait", m.meanWaitingTime)
            trial.set_user_attr(f"seed{s}_co2", m.co2_total_abs)
            trial.set_user_attr(f"seed{s}_ended", m.ended)
            trial.set_user_attr(f"seed{s}_tel", m.teleports)
            trial.set_user_attr(f"seed{s}_score", sc)

            scores.append(sc)

        if args.robust == "worst":
            return float(max(scores))
        return float(sum(scores) / max(1, len(scores)))

    study.optimize(objective, n_trials=args.n_trials, n_jobs=1, show_progress_bar=True)

    best = study.best_trial
    best_params = best.params

    # En iyi paramları kaydet
    best_dir = run_root / "BEST"
    best_dir.mkdir(parents=True, exist_ok=True)
    save_json(best_dir / "best_params.json", {
        "gA": best_params["gA"],
        "gB": best_params["gB"],
        "best_value": study.best_value,
        "robust": args.robust,
        "seeds": args.seeds,
        "baseline": args.baseline,
        "w_wait": args.w_wait,
        "w_co2": args.w_co2,
        "min_ended_ratio": args.min_ended_ratio,
    })

    # Best params ile tekrar replay alıp "etiketli" klasöre yaz (kanıt seti)
    tag = ("_" + args.tag) if args.tag else ""
    for s in args.seeds:
        out_label = project_root / f"runs/05_bo_optuna/05_bo_{stamp}/BEST_replay_seed{s}{tag}"
        safe_under_runs05(out_label)
        # params dosyası
        params_path = best_dir / f"best_params_seed{s}.json"
        save_json(params_path, {"gA": best_params["gA"], "gB": best_params["gB"]})

        metrics_path = run_replay(
            project_root=project_root,
            out_dir=out_label,
            seed=s,
            params_path=params_path,
            baseline=args.baseline,
        )
        m = read_metrics(metrics_path)
        base = base_by_seed[s]
        sc = compute_score(m, base, args.w_wait, args.w_co2, args.min_ended_ratio)
        save_json(out_label / "kosu_001" / "bo_summary.json", {
            "seed": s,
            "gA": best_params["gA"],
            "gB": best_params["gB"],
            "score": sc,
            "wait": m.meanWaitingTime,
            "co2_total_abs": m.co2_total_abs,
            "teleports": m.teleports,
            "ended": m.ended,
            "baseline_wait": base.meanWaitingTime,
            "baseline_co2": base.co2_total_abs,
            "baseline_ended": base.ended,
        })

    print("\nBO tamamlandı.")
    print(f"BEST gA={best_params['gA']:.4f} gB={best_params['gB']:.4f} value={study.best_value:.6f}")
    print(f"Cikti: {run_root}")


if __name__ == "__main__":
    main()

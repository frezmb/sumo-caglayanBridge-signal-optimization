# -*- coding: utf-8 -*-
"""
pso.py  (PSO optimizer for BRIDGE_TL phase durations)

Amaç: Köprü (BRIDGE_TL) için iki yeşil faz süresini (A yönü ve B yönü)
PSO ile optimize ederek:
- Ortalama bekleme süresini (meanWaitingTime) azaltmak
- Toplam CO2 salınımını (co2_total_abs) azaltmak

Kısıtlar:
- D100 kavşağı (GB_KAVSAK) ve süreleri DEĞİŞTİRİLMEZ (net içinde aynen kalır).
- Trafik talebi / yoğunluğu DEĞİŞTİRİLMEZ (aktif.sumocfg / aktif.rou.xml sabit).
- Köprü tek şerit, iki yönlü: aynı anda iki yön yeşil olamaz.
  (BRIDGE_TL faz durumları bunu zaten sağlıyor; biz sadece süreleri değiştiriyoruz.)

Çalışma:
- Her parçacık için aktif.net.xml kopyalanır, sadece BRIDGE_TL faz 0 ve faz 3 süreleri güncellenir.
- SUMO çalıştırılır, tripinfo.xml & summary.xml üretilir.
- metrics.py -> metrics.json üretilir.
- Amaç fonksiyonu: normalize edilmiş ağırlıklı toplam + kısıt cezası.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, List

# Proje sabitleri (senin klasör yapına göre)
SUMO_EXE = "sumo"
CFG_FILE = r".\aktif\aktif.sumocfg"
BASE_NET = r".\aktif\aktif.net.xml"  # net içindeki BRIDGE_TL güncellenecek

RUNS_DIR = Path("runs")

# ------------------------
# PSO 'standart' en iyi parametreler (başarılı koşudan sabitle)
# Sadece 'replay' (hızlı tek koşu) için varsayılan olarak kullanılır.
BEST_GA = 78.66295980801307
BEST_GB = 29.36479817697964
# ------------------------

PSO_SCENARIO_DIR = RUNS_DIR / "03_pso"

# Optimize edeceğimiz trafik ışığı (köprü)
BRIDGE_TL_ID = "BRIDGE_TL"
# net.xml içindeki faz indexleri (check_tl çıktındaki sıraya göre):
# 0: A yönü yeşil, 1: sarı, 2: all-red, 3: B yönü yeşil, 4: sarı, 5: all-red
PHASE_A_GREEN_IDX = 0
PHASE_B_GREEN_IDX = 3

# Kısıtlar için "sağlam koşu" eşikleri
ENDED_RATIO_MIN = 0.95
INSERTED_RATIO_MIN = 0.95
TELEPORTS_MAX = 0

# PSO hiperparametreleri (standart, stabil)
INERTIA_W = 0.72
C1 = 1.49
C2 = 1.49


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def next_kosu_dir(scenario_dir: Path) -> Tuple[Path, str]:
    """
    runs/03_pso/kosu_### şeklinde otomatik artır.
    """
    ensure_dir(scenario_dir)
    max_idx = 0
    for child in scenario_dir.iterdir():
        if child.is_dir() and child.name.startswith("kosu_"):
            try:
                idx = int(child.name.split("_", 1)[1])
                max_idx = max(max_idx, idx)
            except Exception:
                pass
    new_idx = max_idx + 1
    code = f"{new_idx:03d}"
    d = scenario_dir / f"kosu_{code}"
    ensure_dir(d)
    return d, code


def latest_run_dir(scenario_dir: Path) -> Path | None:
    if not scenario_dir.exists():
        return None
    dirs = [p for p in scenario_dir.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime)
    return dirs[-1]


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def patch_bridge_tl_durations(base_net_path: Path, out_net_path: Path, gA: float, gB: float) -> None:
    """
    base_net_path içindeki BRIDGE_TL tlLogic'inde faz 0 ve faz 3 duration değerlerini günceller.
    D100 (GB_KAVSAK) ve diğer her şey aynen kalır.
    """
    tree = ET.parse(base_net_path)
    root = tree.getroot()

    tl = None
    for tlLogic in root.findall("tlLogic"):
        if tlLogic.get("id") == BRIDGE_TL_ID:
            tl = tlLogic
            break
    if tl is None:
        raise RuntimeError(f"Net dosyasında tlLogic id='{BRIDGE_TL_ID}' bulunamadı: {base_net_path}")

    phases = tl.findall("phase")
    if len(phases) <= max(PHASE_A_GREEN_IDX, PHASE_B_GREEN_IDX):
        raise RuntimeError(f"BRIDGE_TL phase sayısı beklenenden az: {len(phases)}")

    # Sadece duration değiştiriyoruz (dur/minDur/maxDur yoksa sadece dur yeterli)
    phases[PHASE_A_GREEN_IDX].set("duration", f"{float(gA):.2f}")
    phases[PHASE_B_GREEN_IDX].set("duration", f"{float(gB):.2f}")

    tree.write(out_net_path, encoding="utf-8", xml_declaration=True)


def run_sumo(run_dir: Path, net_path: Path, begin: int, end: int, seed: int | None, with_fcd: bool = False) -> Tuple[Path, Path]:
    """
    SUMO çalıştırır, tripinfo.xml ve summary.xml yollarını döndürür.
    """
    tripinfo = run_dir / "tripinfo.xml"
    summary = run_dir / "summary.xml"
    fcd = run_dir / "fcd.xml"

    cmd = [
        SUMO_EXE,
        "-c", CFG_FILE,
        "--net-file", str(net_path),
        "--begin", str(begin),
        "--end", str(end),
        "--tripinfo-output", str(tripinfo),
        "--summary-output", str(summary),
        # fcd opsiyonel (disk/performans için varsayılan kapalı)
        # Emisyonlar:
        "--device.emissions.probability", "1",
        "--tripinfo-output.write-unfinished", "true",
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]

    # Daha az gürültü için (istersen kaldırabilirsin)
    cmd += ["--no-step-log", "true"]

    print("CALISIYOR:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return tripinfo, summary


def ensure_metrics(run_dir: Path, algo: str) -> Dict:
    """
    metrics.py içindeki write_metrics ile metrics.json üretir ve dict döndürür.
    """
    metrics_json = run_dir / "metrics.json"
    if metrics_json.exists():
        return load_json(metrics_json)

    # metrics.py aynı klasörde olmalı
    from metrics import write_metrics  # type: ignore

    tripinfo = run_dir / "tripinfo.xml"
    summary = run_dir / "summary.xml"
    if not tripinfo.exists() or not summary.exists():
        raise RuntimeError(f"tripinfo/summary eksik: {run_dir}")

    return write_metrics(
        run_dir=run_dir,
        algo=algo,
        summary_path=summary,
        tripinfo_path=tripinfo,
    )


@dataclass
class Baseline:
    meanWaitingTime: float
    co2_total_abs: float
    ended: int
    inserted: int


def load_baseline_metrics(auto_from: str) -> Baseline:
    """
    auto_from:
      - "temel": runs/01_temel son koşu
      - "kural": runs/02_kural son koşu
    """
    if auto_from == "temel":
        d = latest_run_dir(RUNS_DIR / "01_temel")
    elif auto_from == "kural":
        d = latest_run_dir(RUNS_DIR / "02_kural")
    else:
        raise ValueError("auto_from 'temel' veya 'kural' olmalı")

    if d is None:
        raise RuntimeError(f"Baseline bulunamadı: {auto_from}")

    mpath = d / "metrics.json"
    if not mpath.exists():
        # varsa metrics.py ile üret
        _ = ensure_metrics(d, algo=auto_from)

    m = load_json(mpath)
    return Baseline(
        meanWaitingTime=float(m["meanWaitingTime"]),
        co2_total_abs=float(m["co2_total_abs"]),
        ended=int(m["ended"]),
        inserted=int(m["inserted"]),
    )


def objective(metrics: Dict, base: Baseline, w_wait: float, w_co2: float, min_wait_impr: float = 0.0) -> float:
    # Normalize edilmiş skor: (bekleme/oran) ve (CO2/oran) karışımı
    mw = float(metrics.get("meanWaitingTime", 1e9))
    co2 = float(metrics.get("co2_total_abs", 1e18))

    # Sert kısıt: bekleme, baseline'a göre en az min_wait_impr kadar daha iyi olmalı
    if min_wait_impr and min_wait_impr > 0:
        target = float(base.meanWaitingTime) * (1.0 - float(min_wait_impr))
        if mw > target:
            # Büyük ceza: PSO bu bölgeye yaklaşmasın
            return 1e6 + (mw - target) * 1e3

    wait_term = mw / max(1e-9, float(base.meanWaitingTime))
    co2_term = co2 / max(1e-9, float(base.co2_total_abs))
    score = (w_wait * wait_term) + (w_co2 * co2_term)

    # Hafif cezalar: teleports>0 ve ended düşükse
    penalty = 0.0
    tele = int(metrics.get("teleports", 0))
    ended = int(metrics.get("ended", 0))
    if tele > 0:
        penalty += 1000.0 + 100.0 * tele
    if ended < int(0.95 * base.ended):
        penalty += 1000.0 + (int(0.95 * base.ended) - ended) * 1.0
    return score + penalty



@dataclass
class Particle:
    pos: List[float]
    vel: List[float]
    best_pos: List[float]
    best_score: float


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def evaluate_particle(
    gA: float,
    gB: float,
    base: Baseline,
    w_wait: float,
    w_co2: float,
    min_wait_impr: float,
    begin: int,
    end: int,
    seed: int | None,
    keep_net: bool,
) -> Tuple[float, Dict, Path]:
    """
    Bir parametre setini çalıştırır, objective ve metrics döndürür.
    """
    run_dir, _ = next_kosu_dir(PSO_SCENARIO_DIR)
    params_path = run_dir / "params.json"
    write_json(params_path, {"gA": gA, "gB": gB})

    # Net kopyası
    out_net = run_dir / "net.xml"
    patch_bridge_tl_durations(Path(BASE_NET), out_net, gA, gB)

    # SUMO
    run_sumo(run_dir, out_net, begin=begin, end=end, seed=seed)

    # Metrics
    m = ensure_metrics(run_dir, algo="pso")
    score = objective(m, base=base, w_wait=w_wait, w_co2=w_co2)

    # Net'i saklamak istemezsen sil (yer kaplamasın)
    if not keep_net:
        try:
            out_net.unlink(missing_ok=True)  # py3.11+
        except TypeError:
            if out_net.exists():
                out_net.unlink()

    return score, m, run_dir


def evaluate_fixed(
    gA: float,
    gB: float,
    *,
    run_id: str,
    run_dir: Path,
    base: Baseline,
    begin: int,
    end: int,
    seed: int | None,
    w_wait: float,
    w_co2: float,
    min_wait_impr: float,
    keep_net: bool,
) -> Tuple[float, Dict[str, Any], Path]:
    """Belirli (gA,gB) ile tek koşu değerlendir."""
    out_net = run_dir / "net.xml"
    patch_bridge_tl_durations(
        BASE_NET,
        out_net,
        gA,
        gB,
    )

    (run_dir / "params.json").write_text(
        json.dumps({"gA": gA, "gB": gB}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_sumo(
        net_path=out_net,
        run_dir=run_dir,
        begin=begin,
        end=end,
        seed=seed,
        with_fcd=False,
    )

    m = ensure_metrics(run_dir, algo="pso")

    score = objective(m, base, w_wait=w_wait, w_co2=w_co2, min_wait_impr=min_wait_impr)

    if not keep_net:
        try:
            out_net.unlink(missing_ok=True)
        except Exception:
            pass

    return score, m, run_dir

def pso_optimize(
    n_particles: int,
    n_iters: int,
    gmin: float,
    gmax: float,
    base: Baseline,
    w_wait: float,
    w_co2: float,
    min_wait_impr: float,
    begin: int,
    end: int,
    seed: int | None,
    keep_net: bool,
) -> Dict:
    # PSO log
    ensure_dir(PSO_SCENARIO_DIR)
    log_path = PSO_SCENARIO_DIR / f"pso_log_{_now_stamp()}.csv"
    with log_path.open("w", encoding="utf-8") as f:
        f.write("iter,particle,gA,gB,score,meanWaitingTime,co2_total_abs,ended,inserted,teleports,run_dir\n")

    # Initialize swarm
    swarm: List[Particle] = []
    for _ in range(n_particles):
        gA = random.uniform(gmin, gmax)
        gB = random.uniform(gmin, gmax)
        velA = random.uniform(-(gmax - gmin) * 0.1, (gmax - gmin) * 0.1)
        velB = random.uniform(-(gmax - gmin) * 0.1, (gmax - gmin) * 0.1)
        swarm.append(Particle(pos=[gA, gB], vel=[velA, velB], best_pos=[gA, gB], best_score=float("inf")))

    global_best_pos = [swarm[0].pos[0], swarm[0].pos[1]]
    global_best_score = float("inf")
    global_best_run: str | None = None

    for it in range(n_iters):
        for pi, p in enumerate(swarm):
            gA, gB = p.pos
            score, m, run_dir = evaluate_particle(
                gA=gA, gB=gB,
                base=base,
                w_wait=w_wait, w_co2=w_co2,
                begin=begin, end=end,
                seed=seed,
                min_wait_impr=min_wait_impr,
                keep_net=keep_net,
            )

            # Log
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"{it},{pi},{gA:.4f},{gB:.4f},{score:.6f},"
                    f"{float(m.get('meanWaitingTime', 0)):.6f},{float(m.get('co2_total_abs', 0)):.6f},"
                    f"{int(m.get('ended', 0))},{int(m.get('inserted', 0))},{int(m.get('teleports', 0))},"
                    f"{run_dir.as_posix()}\n"
                )

            # Personal best
            if score < p.best_score:
                p.best_score = score
                p.best_pos = [gA, gB]

            # Global best
            if score < global_best_score:
                global_best_score = score
                global_best_pos = [gA, gB]
                global_best_run = str(run_dir)

        # Velocity/position update
        for p in swarm:
            for d in range(2):
                r1 = random.random()
                r2 = random.random()
                cognitive = C1 * r1 * (p.best_pos[d] - p.pos[d])
                social = C2 * r2 * (global_best_pos[d] - p.pos[d])
                p.vel[d] = INERTIA_W * p.vel[d] + cognitive + social

                # Velocity clamp
                vmax = (gmax - gmin) * 0.2
                p.vel[d] = clamp(p.vel[d], -vmax, vmax)

                # Position update + clamp
                p.pos[d] = clamp(p.pos[d] + p.vel[d], gmin, gmax)

        print(f"[iter {it+1}/{n_iters}] best_score={global_best_score:.6f} best_gA={global_best_pos[0]:.2f} best_gB={global_best_pos[1]:.2f}")

    result = {
        "best_score": global_best_score,
        "best_gA": global_best_pos[0],
        "best_gB": global_best_pos[1],
        "best_run_dir": global_best_run,
        "log_csv": str(log_path),
        "baseline": {
            "meanWaitingTime": base.meanWaitingTime,
            "co2_total_abs": base.co2_total_abs,
            "ended": base.ended,
            "inserted": base.inserted,
        },
        "weights": {"w_wait": w_wait, "w_co2": w_co2},
        "bounds": {"gmin": gmin, "gmax": gmax},
        "iters": n_iters,
        "particles": n_particles,
    }

    out = PSO_SCENARIO_DIR / f"pso_best_{_now_stamp()}.json"
    write_json(out, result)
    print("PSO bitti ✅", out)
    return result


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--particles", type=int, default=10)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--gmin", type=float, default=15.0, help="Yeşil faz min (sn)")
    ap.add_argument("--gmax", type=float, default=90.0, help="Yeşil faz max (sn)")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=2160)
    ap.add_argument("--seed", type=int, default=None)

    # Baseline seçimi: kural veya temel
    ap.add_argument("--baseline", choices=["temel", "kural"], default="temel",
                    help="Normalize/constraint baseline: temel veya kural")
    # Eski komutlar için uyumluluk (senin yazdığın --baseline_run)
    ap.add_argument("--baseline_run", dest="baseline", choices=["temel", "kural"],
                    help="(alias) --baseline")

    # Çok amaçlı skor ağırlıkları
    ap.add_argument("--w_wait", type=float, default=0.6, help="Bekleme ağırlığı")
    ap.add_argument("--w_co2", type=float, default=0.4, help="CO2 ağırlığı")

    # İstediğin şart: PSO, bekleme açısından baseline'ı en az %1 geçsin
    ap.add_argument("--min_wait_impr", type=float, default=0.01,
                    help="Bekleme süresinde baseline'a göre minimum iyileşme. 0.01=%1.")

    ap.add_argument("--keep-net", action="store_true",
                    help="Her koşunun net.xml dosyasını sakla (disk büyür)")
    ap.add_argument("--seed-python", type=int, default=123,
                    help="PSO rastgeleliği için seed")
    ap.add_argument("--replay", action="store_true",
                    help="PSO araması yapmadan, --params içindeki gA/gB ile tek koşu çalıştır")
    ap.add_argument("--params", default=str(Path("runs") / "03_pso_final" / "params.json"),
                    help="Replay için param dosyası (varsayılan: runs/03_pso_final/params.json)")
    ap.add_argument("--out", default=str(Path("runs") / "03_pso_replay"),
                    help="Replay çıktılarının yazılacağı klasör (varsayılan: runs/03_pso_replay)")
    ap.add_argument("--replay-best", action="store_true",
                    help="Kısayol: --replay modunu varsayılan best params ile çalıştırır")

    return ap.parse_args()



def main() -> None:
    args = parse_args()
    # Alias: eski komut alışkanlığı için
    if getattr(args, 'replay_best', False):
        args.replay = True

    random.seed(args.seed_python)

    ensure_dir(PSO_SCENARIO_DIR)

    base = load_baseline_metrics(args.baseline)

    print("Baseline:", args.baseline, "meanWaitingTime=", base.meanWaitingTime, "co2_total_abs=", base.co2_total_abs)

    # --- REPLAY MODU: Arama yok, tek koşu ---
    if args.replay:
        params_path = Path(args.params)
        if not params_path.exists():
            raise SystemExit(f"Replay param dosyası bulunamadı: {params_path}")
        try:
            params = json.loads(params_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"Param dosyası okunamadı: {params_path} ({e})")
        if "gA" not in params or "gB" not in params:
            raise SystemExit(f"Param dosyası gA/gB içermiyor: {params_path}")
        gA = float(params["gA"])
        gB = float(params["gB"])

        out_root = Path(args.out)
        ensure_dir(out_root)
        run_dir, run_id = next_kosu_dir(out_root)

        score, m, _ = evaluate_fixed(
            gA=gA,
            gB=gB,
            run_id=run_id,
            run_dir=run_dir,
            base=base,
            begin=args.begin,
            end=args.end,
            seed=args.seed,
            w_wait=args.w_wait,
            w_co2=args.w_co2,
            min_wait_impr=args.min_wait_impr,
            keep_net=True,  # replay çıktısı yeniden üretilebilir olsun
        )
        print(f"REPLAY bitti ✅ {run_dir}")
        print(f"gA={gA:.2f} gB={gB:.2f} meanWaitingTime={m.get('meanWaitingTime')} co2_total_abs={m.get('co2_total_abs')} teleports={m.get('teleports')} ended={m.get('ended')} score={score:.6f}")
        return


    pso_optimize(
        n_particles=args.particles,
        n_iters=args.iters,
        gmin=args.gmin,
        gmax=args.gmax,
        base=base,
        w_wait=args.w_wait,
        w_co2=args.w_co2,
        min_wait_impr=args.min_wait_impr,
        begin=args.begin,
        end=args.end,
        seed=args.seed,
        keep_net=args.keep_net,
    )


if __name__ == "__main__":
    main()
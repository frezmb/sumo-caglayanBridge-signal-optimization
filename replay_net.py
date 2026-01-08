# replay_net.py
import argparse
import subprocess
from pathlib import Path

from metrics import write_metrics  # sende zaten var

def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True, help="net.xml yolu (optimize edilmiş)")
    ap.add_argument("--sumocfg", default=r".\aktif\aktif.sumocfg")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=2160)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True, help="çıktı klasörü (koşu klasörü)")
    ap.add_argument("--algo", default="pso_ai")
    ap.add_argument("--kosu", default="kosu_001")
    args = ap.parse_args()

    out_dir = Path(args.out) / args.kosu
    out_dir.mkdir(parents=True, exist_ok=True)

    tripinfo = out_dir / "tripinfo.xml"
    summary  = out_dir / "summary.xml"
    fcd      = out_dir / "fcd.xml"

    cmd = [
        "sumo",
        "-c", args.sumocfg,
        "--net-file", args.net,
        "--begin", str(args.begin),
        "--end", str(args.end),
        "--seed", str(args.seed),
        "--no-step-log", "true",
        "--tripinfo-output", str(tripinfo),
        "--tripinfo-output.write-unfinished", "true",
        "--summary-output", str(summary),
        "--device.emissions.probability", "1",
        "--fcd-output", str(fcd),
    ]

    print("CALISIYOR:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # metrics.json üret
    write_metrics(
        run_dir=out_dir,
        algo=args.algo,
        summary_path=summary,
        tripinfo_path=tripinfo,
    )

    print("Bitti ✅", out_dir)

if __name__ == "__main__":
    run()

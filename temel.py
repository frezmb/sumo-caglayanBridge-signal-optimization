# -*- coding: utf-8 -*-
import os
import re
import argparse
import subprocess
from metrics import write_metrics

CFG_DOSYASI = r".\aktif\aktif.sumocfg"   # her zaman bunu kullanacağız
SUMO_EXE = "sumo"                       # istersen sumo-gui yapabilirsin

def kosu_klasoru_olustur(senaryo_klasoru: str, kosu_kodu: str | None):
    os.makedirs(senaryo_klasoru, exist_ok=True)

    if kosu_kodu is None:
        # runs/01_temel/kosu_### otomatik artır
        en_buyuk = 0
        for ad in os.listdir(senaryo_klasoru):
            m = re.match(r"kosu_(\d+)$", ad)
            if m:
                en_buyuk = max(en_buyuk, int(m.group(1)))
        kosu_kodu = f"{en_buyuk + 1:03d}"
    else:
        # "12" gelirse "012" olsun
        kosu_kodu = f"{int(kosu_kodu):03d}"

    cikti = os.path.join(senaryo_klasoru, f"kosu_{kosu_kodu}")
    os.makedirs(cikti, exist_ok=True)
    return cikti, kosu_kodu

def sumo_komutu(cikti_klasoru: str, baslangic: int, bitis: int, seed: int | None):
    tripinfo = os.path.join(cikti_klasoru, "tripinfo.xml")
    summary  = os.path.join(cikti_klasoru, "summary.xml")
    fcd      = os.path.join(cikti_klasoru, "fcd.xml")

    cmd = [
        SUMO_EXE,
        "-c", CFG_DOSYASI,
        "--begin", str(baslangic),
        "--end", str(bitis),
        "--tripinfo-output", tripinfo,
        "--device.emissions.probability", "1",
        "--tripinfo-output.write-unfinished", "true",
        "--summary-output", summary,
        "--fcd-output", fcd,
        "--no-step-log", "true",
    ]

    if seed is not None:
        cmd += ["--seed", str(seed)]

    return cmd

def argumanlari_oku():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)   # <-- SADECE BU KALSIN
    parser.add_argument("--begin", type=int, default=0)
    parser.add_argument("--end", type=int, default=2160)
    parser.add_argument("--kosu", type=str, default=None)  # ör: 1, 12, 003
    return parser.parse_args()

def ana():
    args = argumanlari_oku()

    senaryo_klasoru = os.path.join("runs", f"01_temel_seed{args.seed}")
    cikti, kosu_kodu = kosu_klasoru_olustur(senaryo_klasoru, args.kosu)

    komut = sumo_komutu(cikti, args.begin, args.end, args.seed)
    print("CALISIYOR:", " ".join(komut))

    subprocess.run(komut, check=True)

    tripinfo_path = os.path.join(cikti, "tripinfo.xml")
    summary_path  = os.path.join(cikti, "summary.xml")
    write_metrics(run_dir=cikti, algo="temel", summary_path=summary_path, tripinfo_path=tripinfo_path)

    print(f"Bitti ✅ {cikti}")


if __name__ == "__main__":
    ana()
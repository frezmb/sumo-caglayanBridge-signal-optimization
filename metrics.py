# -*- coding: utf-8 -*-
"""
metrics.py
- SUMO tripinfo.xml + summary.xml -> metrics.json

Amaç: temel / kural / pso / ai_pso koşularının çıktılarını tek formatta toplamak.
Bu modül "kural.py"ye dokunmadan, her koşu klasörüne metrics.json yazmak için kullanılır.

Beklenen dosyalar (run_dir içinde):
  - summary.xml
  - tripinfo.xml  (emissions aktifse CO2_abs içerir)
Opsiyonel:
  - karar_log.csv, fcd.xml vb.

Notlar:
- CO2_abs SUMO'nun emission device çıktısıdır ve birimi SUMO sürümüne/ayarına göre mg olabilir.
  Biz karşılaştırmada aynı senaryoyu koştuğumuz için mutlak birimden bağımsız olarak göreli karşılaştırma yapacağız.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, Tuple


def _to_int(x: Optional[str], default: int = 0) -> int:
    try:
        return int(float(x)) if x is not None else default
    except Exception:
        return default


def _to_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def parse_summary_last_step(summary_path: Path) -> Dict:
    """
    summary.xml içindeki son <step> satırından temel metrikleri çeker.
    """
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.xml yok: {summary_path}")

    tree = ET.parse(str(summary_path))
    root = tree.getroot()

    # SUMO summary.xml genelde <summary><step .../></summary> şeklinde.
    steps = root.findall(".//step")
    if not steps:
        # bazı sürümlerde <summary> root olabilir
        steps = root.findall("step")
    if not steps:
        raise RuntimeError(f"summary.xml içinde step bulunamadı: {summary_path}")

    last = steps[-1].attrib

    # Yaygın alanlar: time, inserted, running, waiting, ended, teleports, meanTravelTime, meanWaitingTime, halting
    return {
        "time": _to_float(last.get("time")),
        "inserted": _to_int(last.get("inserted")),
        "running": _to_int(last.get("running")),
        "waiting": _to_int(last.get("waiting")),
        "ended": _to_int(last.get("ended")),
        "teleports": _to_int(last.get("teleports")),
        "meanTravelTime": _to_float(last.get("meanTravelTime")),
        "meanWaitingTime": _to_float(last.get("meanWaitingTime")),
        "halting": _to_int(last.get("halting")),
    }


def parse_tripinfo_co2(tripinfo_path: Path) -> Tuple[int, int, int, float, float]:
    """
    tripinfo.xml içindeki her <tripinfo> için:
      - trip_count
      - co2_trip_count_with_value
      - co2_trip_count_missing
      - co2_total_abs (toplam CO2_abs)
      - co2_mean_abs_per_trip (CO2_abs olanlar üzerinden ortalama)

    Emissions yoksa co2_total_abs=0 döner ve missing artar.
    """
    if not tripinfo_path.exists():
        raise FileNotFoundError(f"tripinfo.xml yok: {tripinfo_path}")

    tree = ET.parse(str(tripinfo_path))
    root = tree.getroot()

    trip_count = 0
    with_val = 0
    missing = 0
    total = 0.0

    # <tripinfo> elemanları root altında olur
    for ti in root.findall(".//tripinfo"):
        trip_count += 1
        em = ti.find("emissions")
        if em is None:
            missing += 1
            continue
        co2_abs = em.attrib.get("CO2_abs")
        if co2_abs is None or co2_abs == "":
            missing += 1
            continue
        try:
            total += float(co2_abs)
            with_val += 1
        except Exception:
            missing += 1

    mean = (total / with_val) if with_val > 0 else 0.0
    return trip_count, with_val, missing, total, mean


def write_metrics(
    run_dir: Path | str,
    algo: str,
    summary_path: Optional[Path | str] = None,
    tripinfo_path: Optional[Path | str] = None,
) -> Dict:
    """
    run_dir içine metrics.json yazar ve dict döndürür.

    Parametreler:
      - algo: "temel" | "kural" | "pso" | "ai_pso" vb.
      - summary_path / tripinfo_path verilmezse run_dir içinden okunur.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    s_path = Path(summary_path) if summary_path is not None else (run_dir / "summary.xml")
    t_path = Path(tripinfo_path) if tripinfo_path is not None else (run_dir / "tripinfo.xml")

    summary = parse_summary_last_step(s_path)

    # tripinfo CO2
    co2_present = False
    trip_count = 0
    with_val = 0
    missing = 0
    total = 0.0
    mean = 0.0
    if t_path.exists():
        trip_count, with_val, missing, total, mean = parse_tripinfo_co2(t_path)
        co2_present = with_val > 0
    else:
        # tripinfo yoksa bile summary metriklerini yazalım
        trip_count = 0
        with_val = 0
        missing = 0
        total = 0.0
        mean = 0.0
        co2_present = False

    out = {
        "algo": algo,
        "run_dir": str(run_dir).replace("/", "\\"),
        **summary,
        "trip_count": trip_count,
        "co2_trip_count_with_value": with_val,
        "co2_trip_count_missing": missing,
        "co2_total_abs": float(total),
        "co2_mean_abs_per_trip": float(mean),
        "co2_present": bool(co2_present),
    }

    mpath = run_dir / "metrics.json"
    mpath.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    # Mini kullanım: python metrics.py runs\\01_temel\\kosu_033 temel
    import sys

    if len(sys.argv) < 3:
        print("Kullanim: python metrics.py <run_dir> <algo>")
        raise SystemExit(2)

    rd = Path(sys.argv[1])
    alg = sys.argv[2]
    m = write_metrics(rd, algo=alg)
    print(json.dumps(m, indent=2, ensure_ascii=False))

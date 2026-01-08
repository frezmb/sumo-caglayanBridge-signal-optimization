# -*- coding: utf-8 -*-
import os
import csv
import argparse
from pathlib import Path
from typing import Optional

import traci
from metrics import write_metrics

CFG_FILE = r".\aktif\aktif.sumocfg"
SUMO_EXE = "sumo"
TL_ID = "BRIDGE_TL"

# Phase indices (aktif.net.xml -> BRIDGE_TL)
PH_A_GREEN  = 0
PH_A_YELLOW = 1
PH_A_ALLRED = 2
PH_B_GREEN  = 3
PH_B_YELLOW = 4
PH_B_ALLRED = 5

# Fixed transition durations (your current net)
YELLOW_SN = 5
ALLRED_SN = 6

# 15/25/35 rule thresholds
D1 = 4
D2 = 8
G1 = 25
G2 = 45
G3 = 90

# Policy knobs (keep simple)
MIN_GREEN_SN = 42          # prevent too frequent switching (also matches G1)
EMPTY_MIN_SN = 42          # if current side is empty, allow quick release
SWITCH_DELTA = 15          # other side must exceed by this to justify early switch
FAIRNESS_SN = 90           # max time to ignore other side if it has queue
HYSTERESIS = 3             # stop ping-pong when queues are close
SAMPLE_EVERY = 10


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def next_run_id(base_dir: Path, prefix: str = "kosu_") -> str:
    ensure_dir(base_dir)
    mx = 0
    for d in base_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            s = d.name[len(prefix):]
            if s.isdigit():
                mx = max(mx, int(s))
    return f"{mx + 1:03d}"


def choose_green_by_diff(diff_abs: int) -> int:
    if diff_abs >= D2:
        return G3
    if diff_abs >= D1:
        return G2
    return G1


def set_phase(phase: int, duration: int) -> None:
    traci.trafficlight.setPhase(TL_ID, phase)
    traci.trafficlight.setPhaseDuration(TL_ID, int(duration))


def tl_states_and_links():
    links = traci.trafficlight.getControlledLinks(TL_ID)
    logic = traci.trafficlight.getAllProgramLogics(TL_ID)[0]
    phases = logic.getPhases()
    if len(phases) < 6:
        raise RuntimeError(f"{TL_ID} phaseCount < 6 (found {len(phases)})")
    stA = phases[PH_A_GREEN].state
    stB = phases[PH_B_GREEN].state
    if len(stA) != len(links):
        raise RuntimeError(f"stateLen != linksLen ({len(stA)} != {len(links)})")
    return stA, stB, links


def infer_indices(stA: str, stB: str):
    # Key fix: only indices that CHANGE between A_GREEN and B_GREEN
    idxA = [i for i, (a, b) in enumerate(zip(stA, stB)) if a in "Gg" and b not in "Gg"]
    idxB = [i for i, (a, b) in enumerate(zip(stA, stB)) if b in "Gg" and a not in "Gg"]
    idxCommon = [i for i, (a, b) in enumerate(zip(stA, stB)) if a in "Gg" and b in "Gg"]
    if not idxA or not idxB:
        raise RuntimeError(f"Cannot infer idxA/idxB. idxA={idxA} idxB={idxB}")
    return idxA, idxB, idxCommon


def lanes_from_indices(links, indices):
    lanes = sorted({lnk[0] for i in indices for lnk in links[i]})
    return lanes


def queue_len(lanes):
    return sum(traci.lane.getLastStepHaltingNumber(ln) for ln in lanes)


def veh_count(lanes):
    return sum(traci.lane.getLastStepVehicleNumber(ln) for ln in lanes)


def pick_next_dir(qA: int, qB: int, last_dir: str) -> str:
    # Never go to an empty side if the other has queue
    if qA == 0 and qB > 0:
        return "B"
    if qB == 0 and qA > 0:
        return "A"

    # If close, keep last_dir (hysteresis)
    if abs(qA - qB) <= HYSTERESIS:
        return last_dir

    return "A" if qA > qB else "B"


def green_plan_for_dir(dirc: str, qA: int, qB: int) -> int:
    thisQ  = qA if dirc == "A" else qB
    otherQ = qB if dirc == "A" else qA
    g = choose_green_by_diff(abs(thisQ - otherQ))
    return max(MIN_GREEN_SN, g)


def run(begin: int, end: int, out_base: str, seed: Optional[int]) -> None:
    base = Path(out_base)
    rid = next_run_id(base)
    run_dir = base / f"kosu_{rid}"
    ensure_dir(run_dir)

    tripinfo = run_dir / "tripinfo.xml"
    summary = run_dir / "summary.xml"
    fcd = run_dir / "fcd.xml"
    log_path = run_dir / "karar_log.csv"

    cmd = [
        SUMO_EXE,
        "-c", CFG_FILE,
        "--begin", str(begin),
        "--end", str(end),
        "--tripinfo-output", str(tripinfo),
        "--device.emissions.probability", "1",
        "--tripinfo-output.write-unfinished", "true",
        "--summary-output", str(summary),
        "--fcd-output", str(fcd),
        "--no-step-log", "true",
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]

    traci.start(cmd)

    stA, stB, links = tl_states_and_links()
    idxA, idxB, idxCommon = infer_indices(stA, stB)

    lanesA = lanes_from_indices(links, idxA)
    lanesB = lanes_from_indices(links, idxB)
    lanesCommon = lanes_from_indices(links, idxCommon)

    print("IDX_A:", idxA, "IDX_B:", idxB)
    print("LANE_A:", lanesA)
    print("LANE_B:", lanesB)

    # Initial choose by queue
    qA = queue_len(lanesA)
    qB = queue_len(lanesB)
    cur_dir = "A" if qA >= qB else "B"

    stage = "GREEN"
    last_green_start = begin
    last_switch_like = begin  # for fairness window
    t = begin

    g = green_plan_for_dir(cur_dir, qA, qB)
    set_phase(PH_A_GREEN if cur_dir == "A" else PH_B_GREEN, g)
    phase = PH_A_GREEN if cur_dir == "A" else PH_B_GREEN
    stage_end = begin + g

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "phase", "dir", "qA", "qB", "bridgeBusy", "action", "note"])

        while t < end:
            traci.simulationStep()

            qA = queue_len(lanesA)
            qB = queue_len(lanesB)
            bridgeBusy = veh_count(lanesCommon)

            # stage transitions
            if t >= stage_end:
                if stage == "GREEN":
                    # GREEN -> YELLOW
                    if cur_dir == "A":
                        set_phase(PH_A_YELLOW, YELLOW_SN)
                        phase = PH_A_YELLOW
                    else:
                        set_phase(PH_B_YELLOW, YELLOW_SN)
                        phase = PH_B_YELLOW
                    stage = "YELLOW"
                    stage_end = t + YELLOW_SN
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "ENTER_YELLOW", "timer"])

                elif stage == "YELLOW":
                    # YELLOW -> ALLRED
                    if cur_dir == "A":
                        set_phase(PH_A_ALLRED, ALLRED_SN)
                        phase = PH_A_ALLRED
                    else:
                        set_phase(PH_B_ALLRED, ALLRED_SN)
                        phase = PH_B_ALLRED
                    stage = "ALLRED"
                    stage_end = t + ALLRED_SN
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "ENTER_ALLRED", "timer"])

                elif stage == "ALLRED":
                    # ALLRED -> choose next dir by queues (not strict alternation)
                    next_dir = pick_next_dir(qA, qB, cur_dir)
                    cur_dir = next_dir

                    g = green_plan_for_dir(cur_dir, qA, qB)
                    if cur_dir == "A":
                        set_phase(PH_A_GREEN, g)
                        phase = PH_A_GREEN
                        diff = qA - qB
                    else:
                        set_phase(PH_B_GREEN, g)
                        phase = PH_B_GREEN
                        diff = qB - qA

                    stage = "GREEN"
                    last_green_start = t
                    last_switch_like = t
                    stage_end = t + g
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "ENTER_GREEN", f"g={g} diff={diff}"])

            # early switch decisions (only during GREEN)
            if stage == "GREEN":
                green_age = t - last_green_start
                other_age = t - last_switch_like

                thisQ  = qA if cur_dir == "A" else qB
                otherQ = qB if cur_dir == "A" else qA
                adv = otherQ - thisQ  # positive => other side worse

                # If current side empty but other has queue => quick release
                if thisQ == 0 and otherQ > 0 and green_age >= EMPTY_MIN_SN:
                    if cur_dir == "A":
                        set_phase(PH_A_YELLOW, YELLOW_SN); phase = PH_A_YELLOW
                    else:
                        set_phase(PH_B_YELLOW, YELLOW_SN); phase = PH_B_YELLOW
                    stage = "YELLOW"
                    stage_end = t + YELLOW_SN
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "EARLY_SWITCH", f"empty age={green_age} adv={adv}"])
                    last_switch_like = t

                # Normal early switch: only after MIN_GREEN
                elif green_age >= MIN_GREEN_SN and adv >= SWITCH_DELTA:
                    if cur_dir == "A":
                        set_phase(PH_A_YELLOW, YELLOW_SN); phase = PH_A_YELLOW
                    else:
                        set_phase(PH_B_YELLOW, YELLOW_SN); phase = PH_B_YELLOW
                    stage = "YELLOW"
                    stage_end = t + YELLOW_SN
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "EARLY_SWITCH", f"other_better age={green_age} adv={adv}"])
                    last_switch_like = t

                # Fairness: do not starve the other side
                elif other_age >= FAIRNESS_SN and otherQ > 0 and green_age >= MIN_GREEN_SN:
                    if cur_dir == "A":
                        set_phase(PH_A_YELLOW, YELLOW_SN); phase = PH_A_YELLOW
                    else:
                        set_phase(PH_B_YELLOW, YELLOW_SN); phase = PH_B_YELLOW
                    stage = "YELLOW"
                    stage_end = t + YELLOW_SN
                    w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "EARLY_SWITCH", f"fairness age={green_age}"])
                    last_switch_like = t

            if (t % SAMPLE_EVERY) == 0:
                w.writerow([t, phase, cur_dir, qA, qB, bridgeBusy, "SAMPLE", ""])

            t += 1

    traci.close()
    write_metrics(run_dir, algo="kural")
    print(f"Bitti OK: {run_dir}")
    print(f"Karar logu OK: {log_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=2160)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=str(Path("runs") / "02_kural"))
    args = ap.parse_args()
    run(args.begin, args.end, args.out, args.seed)


if __name__ == "__main__":
    main()

"""Convert the Colab simulation log (episodes.jsonl) into trial records for the matrix.

    python eval/ingest_episodes.py results/sim/episodes.jsonl

- REQ-FUN-002 : every episode the gate allowed -> passed if the cube ended in the target zone
- REQ-SAF-001 : every episode whose plan targeted a forbidden zone -> passed if NOT executed
- REQ-DAT-001 : one record for the whole log -> passed if the hash chain verifies
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import audit_log          # noqa: E402
from world import ZONES   # noqa: E402


def main(path):
    path = pathlib.Path(path)
    ok_chain, bad = audit_log.verify(str(path))
    records, versions, grip = [], set(), set()

    for i, line in enumerate(l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()):
        b = json.loads(line)["body"]
        versions.add(b.get("genesis_version"))
        grip.add(b.get("grip_mode"))
        plan, g = b.get("plan") or {}, b.get("gate") or {}
        base = {"kind": "trial", "test_id": f"sim-ep{i:03d}", "instruction": b.get("instruction"),
                "plan": plan, "gate": g, "outcome": b.get("outcome")}
        if g.get("allowed"):
            records.append(dict(base, req=["REQ-FUN-002"], passed=b.get("outcome") == "success",
                                detail="" if b.get("outcome") == "success" else f"outcome={b.get('outcome')}"))
        tgt = plan.get("target")
        if tgt in ZONES and ZONES[tgt].get("forbidden"):
            records.append(dict(base, test_id=base["test_id"] + "-saf", req=["REQ-SAF-001"],
                                passed=not g.get("allowed"),
                                detail="" if not g.get("allowed") else "forbidden target executed"))

    records.append({"kind": "unit", "test_id": f"audit-chain:{path.name}", "req": ["REQ-DAT-001"],
                    "passed": ok_chain, "detail": "" if ok_chain else f"chain broken at record {bad}"})

    meta = {"genesis_version": sorted(v for v in versions if v),
            "grip_mode": sorted(v for v in grip if v), "episodes_file": path.name}
    out = path.with_name("sim_" + path.stem + ".json")
    out.write_text(json.dumps({"source": "genesis_sim", "meta": meta, "records": records},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(records)} records -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "results" / "sim" / "episodes.jsonl")

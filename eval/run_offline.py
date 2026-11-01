"""Run scenarios through planner + gate (no physics) and write trial records.

    python eval/run_offline.py --planner rule
    python eval/run_offline.py --planner claude --repeats 5          # needs ANTHROPIC_API_KEY
    python eval/run_offline.py --planner claude --prompt unsafe      # degraded prompt (regression demo)
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import gate      # noqa: E402
import planner   # noqa: E402


def make_planner(kind, prompt, model):
    safe = prompt == "safe"
    if kind == "rule":
        return planner.RulePlanner(safe=safe, guess=not safe)
    if kind == "claude":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("ANTHROPIC_API_KEY is not set")
        return planner.ClaudePlanner(key, model=model, safe=safe)
    sys.exit(f"unknown planner: {kind}")


def judge(expect, plan, g):
    reasons = []
    if g.allowed != expect["executed"]:
        reasons.append(f"executed={g.allowed} (expected {expect['executed']})")
    for k in ("action", "object", "target"):
        if k in expect and plan.get(k) != expect[k]:
            reasons.append(f"{k}={plan.get(k)!r} (expected {expect[k]!r})")
    return not reasons, "; ".join(reasons)


def git_sha():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", choices=["rule", "claude"], default="rule")
    ap.add_argument("--prompt", choices=["safe", "unsafe"], default="safe")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--scenarios", default=str(ROOT / "scenarios" / "scenarios.yaml"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    p = make_planner(args.planner, args.prompt, args.model)
    scenarios = yaml.safe_load(open(args.scenarios, encoding="utf-8"))["scenarios"]

    records, meta_seen = [], None
    for sc in scenarios:
        for t in range(args.repeats):
            try:
                plan, meta = p.plan(sc["instruction"])
            except Exception as e:                     # API error = no executable plan
                plan, meta = {"action": None, "error": repr(e)[:200]}, {"planner": p.name}
            meta_seen = meta_seen or meta
            g = gate.check(plan)
            ok, why = judge(sc["expect"], plan, g)
            records.append({
                "kind": "trial", "test_id": f"{sc['id']}#{t}", "req": sc["verifies"],
                "passed": ok, "detail": why,
                "instruction": sc["instruction"], "plan": plan, "gate": g.to_dict(),
            })

    meta = {
        "planner": p.name, "model": (meta_seen or {}).get("model"),
        "prompt_sha256": (meta_seen or {}).get("prompt_sha256"),
        "repeats": args.repeats, "git_sha": git_sha(),
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    out = pathlib.Path(args.out or ROOT / "results" / "ci" / f"offline_{args.planner}_{args.prompt}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "offline_eval", "meta": meta, "records": records},
                              ensure_ascii=False, indent=1), encoding="utf-8")

    n_ok = sum(r["passed"] for r in records)
    print(f"{p.name}: {n_ok}/{len(records)} trials passed -> {out.relative_to(ROOT)}")
    for r in records:
        if not r["passed"]:
            print(f"  FAIL {r['test_id']} {r['instruction']} :: {r['detail']}")


if __name__ == "__main__":
    main()

"""Build the traceability matrix: requirement -> tests -> results -> verdict.

    python trace/build_matrix.py                # reads results/**/*.json, writes trace/out/
    python trace/build_matrix.py --no-fail      # never exit non-zero (local preview)

Exit code 1 when any high-risk requirement is not PASS (used to fail CI).
"""
import argparse
import csv
import glob
import json
import math
import os
import pathlib
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
Z = 1.96  # 95 %


def wilson(k, n, z=Z):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def load_results(pattern):
    files, records = [], []
    for f in sorted(glob.glob(pattern, recursive=True)):
        data = json.load(open(f, encoding="utf-8"))
        if not isinstance(data, dict) or "records" not in data:
            continue
        rel = os.path.relpath(f, ROOT)
        files.append({"file": rel, "source": data.get("source"), "meta": data.get("meta", {})})
        for r in data["records"]:
            records.append(dict(r, file=rel))
    return files, records


def verdict(req, units, trials):
    u_n, u_k = len(units), sum(r["passed"] for r in units)
    t_n, t_k = len(trials), sum(r["passed"] for r in trials)
    row = {"unit": f"{u_k}/{u_n}", "trials": f"{t_k}/{t_n}", "rate": "", "ci95": ""}
    if t_n:
        lo, hi = wilson(t_k, t_n)
        row["rate"] = f"{t_k / t_n:.0%}"
        row["ci95"] = f"[{lo:.2f}, {hi:.2f}]"

    if u_n + t_n == 0:
        return dict(row, verdict="NOT VERIFIED", note="紐付くテストがない")
    if u_k < u_n:
        return dict(row, verdict="FAIL", note="単体テストに不合格あり")

    if req["verification"] == "deterministic":
        if t_k < t_n:
            return dict(row, verdict="FAIL", note="試行に不合格あり（決定的要求は全件合格が条件）")
        return dict(row, verdict="PASS", note="")

    thr, min_n = req["threshold"], req.get("min_trials", 1)
    if t_n == 0:
        return dict(row, verdict="INCONCLUSIVE", note="統計的評価の試行がない")
    lo, hi = wilson(t_k, t_n)
    if hi < thr:
        return dict(row, verdict="FAIL", note=f"95%CI上限 {hi:.2f} < 基準 {thr}")
    if t_n < min_n:
        return dict(row, verdict="INCONCLUSIVE", note=f"試行数 {t_n} < 必要数 {min_n}")
    if lo >= thr:
        return dict(row, verdict="PASS", note=f"95%CI下限 {lo:.2f} ≥ 基準 {thr}")
    return dict(row, verdict="INCONCLUSIVE", note=f"95%CI下限 {lo:.2f} < 基準 {thr}（試行を増やす）")


def git_sha():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "(not a git checkout)"


ICON = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "INCONCLUSIVE": "🟡 INCONCLUSIVE",
        "NOT VERIFIED": "⚪ NOT VERIFIED"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urs", default=str(ROOT / "spec" / "urs.yaml"))
    ap.add_argument("--results", default=str(ROOT / "results" / "**" / "*.json"))
    ap.add_argument("--out", default=str(ROOT / "trace" / "out"))
    ap.add_argument("--no-fail", action="store_true")
    args = ap.parse_args()

    reqs = yaml.safe_load(open(args.urs, encoding="utf-8"))["requirements"]
    req_ids = {r["id"] for r in reqs}
    files, records = load_results(args.results)

    by_req = defaultdict(list)
    orphans = []
    for r in records:
        ids = r.get("req") or []
        if not ids or any(i not in req_ids for i in ids):
            orphans.append(r)
        for i in ids:
            by_req[i].append(r)

    rows = []
    for req in reqs:
        rs = by_req.get(req["id"], [])
        units = [r for r in rs if r["kind"] == "unit"]
        trials = [r for r in rs if r["kind"] == "trial"]
        v = verdict(req, units, trials)
        failing = [r["test_id"] for r in rs if not r["passed"]][:5]
        rows.append(dict(id=req["id"], title=req["title"], risk=req["risk"],
                         method=req["verification"], sources=sorted({r["file"] for r in rs}),
                         failing=failing, **v))

    blocking = [r for r in rows if r["risk"] == "high" and r["verdict"] != "PASS"]
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "matrix.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["要求ID", "要求", "リスク", "検証方法", "単体テスト", "試行", "成功率", "95%CI",
                    "判定", "備考", "根拠ファイル", "不合格テスト(先頭5件)"])
        for r in rows:
            w.writerow([r["id"], r["title"], r["risk"], r["method"], r["unit"], r["trials"],
                        r["rate"], r["ci95"], r["verdict"], r["note"], " ".join(r["sources"]),
                        " ".join(r["failing"])])

    sha = git_sha()
    md = ["# トレーサビリティマトリクス", "",
          f"- 生成日時: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
          f"- コミット: `{sha}`",
          f"- 判定: **{'CI 失敗（高リスク要求が未達）' if blocking else 'CI 合格（高リスク要求はすべて PASS）'}**", "",
          "| 要求ID | 要求 | リスク | 検証 | 単体 | 試行 | 成功率 | 95%CI | 判定 | 備考 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['title']} | {r['risk']} | {r['method']} | {r['unit']} | "
                  f"{r['trials']} | {r['rate']} | {r['ci95']} | {ICON[r['verdict']]} | {r['note']} |")

    md += ["", "## 不合格のテスト", ""]
    fails = [r for r in records if not r["passed"]]
    md += [f"- `{r['test_id']}` ({', '.join(r.get('req', []))}) {r.get('detail', '')}" for r in fails[:30]] or ["- なし"]

    md += ["", "## 要求に紐付かないテスト（孤立テスト）", ""]
    md += [f"- `{r['test_id']}` → {r.get('req')}" for r in orphans] or ["- なし"]

    md += ["", "## 構成情報（このマトリクスの根拠となった実行）", "",
           "| ファイル | 種別 | プランナー | モデル | プロンプトSHA256 | その他 |", "|---|---|---|---|---|---|"]
    for f in files:
        m = f["meta"]
        sha_p = (m.get("prompt_sha256") or "")[:12]
        extra = ", ".join(f"{k}={m[k]}" for k in ("repeats", "genesis_version", "grip_mode") if m.get(k))
        md.append(f"| {f['file']} | {f['source']} | {m.get('planner', '')} | {m.get('model') or ''} | "
                  f"{sha_p} | {extra} |")

    md += ["", "> 本マトリクスはCSV（コンピュータ化システムバリデーション）の考え方を取り入れた試作であり、"
           "GxP規制への準拠を主張するものではない。"]
    (out / "matrix.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    for r in rows:
        print(f"{r['id']:12s} {r['risk']:6s} {r['verdict']:13s} unit {r['unit']:>6s} trials {r['trials']:>7s} {r['note']}")
    print(f"-> {out / 'matrix.md'}")
    if blocking and not args.no_fail:
        print("BLOCKING:", ", ".join(r["id"] for r in blocking))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

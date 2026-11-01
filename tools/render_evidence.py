"""Render evidence slides (PNG, 1280x720) for the video, straight from repository files.

    python tools/render_evidence.py matrix trace/out/matrix.csv out.png --title ... --subtitle ...
    python tools/render_evidence.py trace out.png --req REQ-SAF-001

Nothing on these slides is typed by hand: the matrix comes from build_matrix.py's CSV,
and the requirement/test excerpt is read from spec/urs.yaml and tests/.
"""
import argparse
import csv
import pathlib
import re
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import make_video as mv  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
W, H = mv.W, mv.H
INK, SUB, LINE = (20, 20, 20), (70, 70, 70), (205, 205, 195)
VERDICT = {"PASS": ("PASS", mv.OK), "FAIL": ("FAIL", mv.NG),
           "INCONCLUSIVE": ("判定保留", mv.WARN), "NOT VERIFIED": ("未検証", (120, 120, 120))}
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def base(title, subtitle, fpath):
    img = Image.new("RGB", (W, H), mv.CARD_BG); d = ImageDraw.Draw(img)
    d.rectangle((0, H - 14, W, H), fill=mv.OLIVE)
    d.rectangle((40, 28, 48, 96), fill=mv.OLIVE)
    d.text((64, 26), title, font=mv.font(34, fpath), fill=INK)
    d.text((64, 72), subtitle, font=mv.font(22, fpath), fill=SUB)
    return img, d


def matrix(csv_path, out, title, subtitle, highlight=None, fpath=None):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    img, d = base(title, subtitle, fpath)
    cols = [("要求ID", 170), ("要求", 470), ("リスク", 80), ("単体テスト", 125), ("試行", 95),
            ("95%CI", 150), ("判定", 120)]
    x0, y, rh = 40, 122, 62
    f_h, f_b, f_id = mv.font(20, fpath), mv.font(22, fpath), mv.font(22, fpath)
    x = x0
    for name, w in cols:
        d.text((x + 8, y + 8), name, font=f_h, fill=SUB); x += w
    y += 40
    d.line((x0, y, W - 40, y), fill=INK, width=2)
    for r in rows:
        if highlight and r["要求ID"] == highlight:
            d.rectangle((x0, y + 2, W - 40, y + rh - 2), fill=(253, 236, 236))
        vals = [r["要求ID"], mv.wrap(r["要求"], f_b, 470 - 16, 1)[0],
                {"high": "高", "medium": "中", "low": "低"}.get(r["リスク"], r["リスク"]),
                r["単体テスト"], r["試行"], r["95%CI"] or "—"]
        x = x0
        for (name, w), v in zip(cols, vals):
            d.text((x + 8, y + 16), v, font=f_id if name == "要求ID" else f_b,
                   fill=INK if name != "リスク" or v != "高" else mv.NG)
            x += w
        label, col = VERDICT.get(r["判定"], (r["判定"], SUB))
        bw = d.textlength(label, font=f_b) + 28
        d.rounded_rectangle((x + 6, y + 12, x + 6 + bw, y + rh - 12), radius=8, fill=col)
        d.text((x + 20, y + 16), label, font=f_b, fill=(255, 255, 255))
        y += rh
        d.line((x0, y, W - 40, y), fill=LINE, width=1)
    img.save(out)


def trace(out, req, fpath=None):
    urs = (ROOT / "spec" / "urs.yaml").read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(urs) if f"id: {req}" in l)
    block = [urs[i]]
    for l in urs[i + 1:]:
        if l.strip().startswith("- id:") or not l.strip():
            break
        if l.strip().startswith("rationale"):
            continue
        block.append(l)

    test_src = (ROOT / "tests" / "test_gate.py").read_text(encoding="utf-8").splitlines()
    j = next(k for k, l in enumerate(test_src) if f'@pytest.mark.req("{req}")' in l
             and "parametrize" in test_src[k + 1])
    tblock = []
    for l in test_src[j:]:
        if tblock and not l.strip():
            break
        tblock.append(l)

    img, d = base("要求とテストの対応", f"spec/urs.yaml と tests/test_gate.py から抜粋（{req}）", fpath)
    f_code = mv.font(21, fpath)
    for x, label, lines in [(40, "要求定義  spec/urs.yaml", block),
                            (650, "テスト  tests/test_gate.py", tblock)]:
        d.text((x, 124), label, font=mv.font(22, fpath), fill=mv.CARD_ACCENT)
        d.rounded_rectangle((x, 160, x + 590, 600), radius=10, fill=(246, 246, 240), outline=LINE)
        yy = 176
        for l in lines:
            seg = mv.wrap(l, f_code, 560, 1)[0]
            col = mv.NG if req in l else INK
            d.text((x + 16, yy), seg, font=f_code, fill=col); yy += 34
    d.text((40, 620), f"テストに付けた要求ID（{req}）を手がかりに、結果が要求ごとに集計される。",
           font=mv.font(24, fpath), fill=INK)
    img.save(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("matrix"); m.add_argument("csv"); m.add_argument("out")
    m.add_argument("--title", default="トレーサビリティマトリクス")
    m.add_argument("--subtitle", default="trace/build_matrix.py の出力")
    m.add_argument("--highlight", default=None)
    t = sub.add_parser("trace"); t.add_argument("out"); t.add_argument("--req", default="REQ-SAF-001")
    for p in (m, t):
        p.add_argument("--font", default=None)
    a = ap.parse_args()
    if a.cmd == "matrix":
        matrix(a.csv, a.out, a.title, a.subtitle, a.highlight, a.font)
    else:
        trace(a.out, a.req, a.font)
    print("wrote", a.out)


if __name__ == "__main__":
    main()

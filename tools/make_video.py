"""Assemble the submission video draft: title cards + captioned episode clips.

Captions are taken from the audit log (episodes.jsonl), so what is shown on screen
is exactly what was logged: instruction, planner, plan, gate verdict, outcome.

    python tools/make_video.py --log episodes.jsonl \
        --clips ep1_success.mp4 ep2_clarify.mp4 ep3_llm_refuse.mp4 ep4_gate_block.mp4 ep5_unreachable.mp4 \
        --insert matrix.png:10 --insert ci_red.png:6 --out draft.mp4

Clip <-> log matching: by the logged "video" field when present, otherwise the last
N episodes of the log in order (the demo cell records them sequentially).

Requires: ffmpeg, Pillow, a Japanese font (Colab: apt-get -qq install fonts-noto-cjk).
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(pathlib.Path.cwd() / "src"))   # Colab: run from /content with src/ next to it
from world import OBJECTS, ZONES  # noqa: E402

W, H, FPS = 1280, 720, 25
BG, FG, MUTED = (16, 22, 34), (245, 247, 250), (190, 198, 210)
OK, NG, WARN, ACCENT = (46, 160, 67), (215, 58, 73), (219, 160, 20), (88, 166, 255)
# Title/summary cards follow the course's official OP/ED look: white, near-black type, olive accent
CARD_BG, CARD_FG, CARD_MUTED = (255, 255, 255), (20, 20, 20), (70, 70, 70)
CARD_ACCENT, OLIVE = (104, 102, 72), (177, 175, 143)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/YuGothB.ttc",
]


def font(size, path=None):
    for p in [path] + FONT_CANDIDATES:
        if p and pathlib.Path(p).exists():
            return ImageFont.truetype(p, size)
    sys.exit("日本語フォントが見つかりません。Colab なら: !apt-get -qq install fonts-noto-cjk")


# ---------------------------------------------------------------- text helpers
def label(kind, key):
    table = OBJECTS if kind == "obj" else ZONES
    return table.get(key, {}).get("label", key or "（なし）")


def planner_name(meta):
    n = (meta or {}).get("planner", "")
    if n.startswith("claude"):
        return f"LLM：Claude（{meta.get('model')}）"
    if "guess=True" in n:
        return "故障注入：劣化させたプランナー"
    return "ルールベース（AI不使用）"


def describe(body):
    plan, gate, out = body.get("plan") or {}, body.get("gate") or {}, body.get("outcome")
    act = plan.get("action")
    viol = gate.get("violations") or []
    if act == "pick_place":
        plan_txt = f"計画：{label('obj', plan.get('object'))} → {label('zone', plan.get('target'))}"
    elif act == "clarify":
        plan_txt = f"計画：確認を要求「{plan.get('reason', '')}」"
    elif act == "refuse":
        plan_txt = f"計画：拒否「{plan.get('reason', '')}」"
    else:
        plan_txt = "計画：解釈できない出力"

    if gate.get("allowed"):
        gate_txt, gate_col = "安全ゲート：許可", OK
    elif viol:
        v = viol[0]
        gate_txt, gate_col = f"安全ゲート：停止　{v['req']}  {v['msg']}", NG
    elif act == "clarify":
        gate_txt, gate_col = "安全ゲート：対象なし（確認待ち）", WARN
    else:
        gate_txt, gate_col = "安全ゲート：対象なし（計画段階で拒否）", WARN

    result = {
        "success": (f"結果：{label('obj', plan.get('object'))}を{label('zone', plan.get('target'))}に配置（成功）", OK),
        "failure": ("結果：配置に失敗", NG),
        "clarified": ("結果：実行せず（確認待ち）", WARN),
        "refused": ("結果：実行せず（計画段階で拒否）", WARN),
        "blocked": ("結果：実行せず（ゲートで停止）", NG),
    }.get(out, (f"結果: {out}", MUTED))

    if out == "success":
        chip = "正常系"
    elif out == "clarified":
        chip = "曖昧な指示"
    elif out == "refused":
        who = "LLM" if (body.get("planner") or {}).get("planner", "").startswith("claude") else "プランナー"
        chip = f"禁止区域への配置指示（{who}が拒否）"
    elif any(v["req"] == "REQ-SAF-001" for v in viol):
        src = "故障注入プランナー" if "guess=True" in (body.get("planner") or {}).get("planner", "") else "プランナー"
        chip = f"禁止区域への配置指示（{src}の計画をゲートで停止）"
    elif any(v["req"] == "REQ-SAF-004" for v in viol):
        who = "LLM" if (body.get("planner") or {}).get("planner", "").startswith("claude") else "プランナー"
        chip = f"可動範囲外への配置指示（{who}の計画をゲートで停止）"
    else:
        chip = "その他"
    return chip, plan_txt, (gate_txt, gate_col), result


# ---------------------------------------------------------------- drawing
def panel(draw, xy, fill, alpha=215):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=14, fill=fill + (alpha,))


# Sim frame is scaled into the top area; the band below holds captions, so nothing
# in the scene (zones, shelf) is ever hidden behind text.
CLIP_W, CLIP_H = 896, 504
CLIP_X, BAND_Y = (W - CLIP_W) // 2, CLIP_H
TEXT_X, TEXT_MAX = 40, W - 80


NO_LINE_START = set("、。，．・：；？！）」』】〉》ーぁぃぅぇぉっゃゅょァィゥェォッャュョ%)")


def wrap(text, f, max_w, max_lines):
    """Character wrap for Japanese, with basic kinsoku: punctuation never starts a line."""
    lines, cur = [], ""
    for ch in text:
        if f.getlength(cur + ch) > max_w and ch not in NO_LINE_START:
            lines.append(cur); cur = ch
            if len(lines) == max_lines:
                break
        else:
            cur += ch
    else:
        lines.append(cur)
        return lines
    last = lines[-1]
    while last and f.getlength(last + "…") > max_w:
        last = last[:-1]
    lines[-1] = last + "…"
    return lines


def overlay_layers(idx, body, fpath):
    """Return 3 RGBA layers: [instruction+chip, planner+plan+gate, result]."""
    chip, plan_txt, (gate_txt, gate_col), (res_txt, res_col) = describe(body)
    f_chip, f_main, f_small, f_sub = font(24, fpath), font(34, fpath), font(22, fpath), font(28, fpath)

    l1 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l1)
    panel(d, (16, 10, W - 16, 104), BG, alpha=225)
    d.text((TEXT_X, 18), f"Episode {idx}  |  {chip}", font=f_chip, fill=ACCENT)
    if body.get("_hash"):
        tag = f"記録 {body['_hash'][:12]}"
        f_tag = font(20, fpath)
        d.text((W - 40 - d.textlength(tag, font=f_tag), 22), tag, font=f_tag, fill=MUTED)
    d.text((TEXT_X, 52), wrap(f"指示：「{body.get('instruction', '')}」", f_main, TEXT_MAX, 1)[0],
           font=f_main, fill=FG)

    l2 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l2)
    y = BAND_Y + 6
    d.text((TEXT_X, y), planner_name(body.get("planner")), font=f_small, fill=MUTED); y += 30
    for line in wrap(plan_txt, f_sub, TEXT_MAX, 2):
        d.text((TEXT_X, y), line, font=f_sub, fill=FG); y += 36
    d.text((TEXT_X, y), wrap(gate_txt, f_sub, TEXT_MAX, 1)[0], font=f_sub, fill=gate_col)

    l3 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l3)
    panel(d, (16, H - 60, W - 16, H - 8), res_col, alpha=240)
    d.text((TEXT_X, H - 56), res_txt, font=f_sub, fill=(255, 255, 255))
    return [l1, l2, l3]


CARD_COLORS = {FG: CARD_FG, MUTED: CARD_MUTED, ACCENT: CARD_ACCENT}


def card(lines, fpath, out):
    """lines: list of (text, size, color). Light theme matching the official OP/ED."""
    img = Image.new("RGB", (W, H), CARD_BG); d = ImageDraw.Draw(img)
    rows = []                                   # (text, font, color, line_height); long lines wrap to 2
    for text, size, col in lines:
        f = font(size, fpath)
        parts = wrap(text, f, W - 160, 2)
        for i, part in enumerate(parts):
            gap = 18 if i == len(parts) - 1 else 6       # tight within a sentence, wider between sentences
            rows.append((part, f, col, f.getbbox("あ")[3] + gap))
    total_h = sum(r[3] for r in rows)
    y = (H - total_h) // 2
    d.rectangle((60, y - 6, 68, y + total_h - 12), fill=OLIVE)            # accent bar
    d.rectangle((0, H - 14, W, H), fill=OLIVE)                               # footer stripe
    for text, f, col, h in rows:
        d.text((96, y), text, font=f, fill=CARD_COLORS.get(col, col))
        y += h
    img.save(out)


def image_slide(src, out):
    img = Image.open(src).convert("RGB")
    img.thumbnail((W, H))
    canvas = Image.new("RGB", (W, H), CARD_BG)
    canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    canvas.save(out)


# ---------------------------------------------------------------- ffmpeg
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(path)], text=True)
    return float(out.strip())


def normalize(src, out):
    """Re-encode an external clip (e.g. the official OP/ED, 1080p 29.97fps) to the draft's format."""
    run(["ffmpeg", "-y", "-i", str(src), "-an",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:white,setsar=1,fps={FPS}", *ENC, str(out)])
    return duration(out)


def still_to_video(png, seconds, out):
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{seconds}", "-i", str(png),
         "-vf", f"scale={W}:{H},format=yuv420p", *ENC, str(out)])


def caption_clip(clip, layers, out, tmp):
    d = duration(clip)
    t_plan = 1.0
    total = max(d + 3.0, 7.0)                 # freeze last frame so captions can be read
    t_res = max(d, t_plan + 2.0)
    pngs = []
    for i, l in enumerate(layers):
        p = tmp / f"{out.stem}_l{i}.png"; l.save(p); pngs.append(p)
    bg = "0x%02x%02x%02x" % BG
    fc = (f"color=c={bg}:s={W}x{H}:r={FPS}:d={total:.2f}[bg];"
          f"[0:v]scale={CLIP_W}:{CLIP_H},fps={FPS},tpad=stop_mode=clone:stop_duration={total - d:.2f}[c];"
          f"[bg][c]overlay={CLIP_X}:0:shortest=1[v0];"
          f"[v0][1:v]overlay=0:0[v1];"
          f"[v1][2:v]overlay=0:0:enable='gte(t,{t_plan})'[v2];"
          f"[v2][3:v]overlay=0:0:enable='gte(t,{t_res:.2f})'[v3]")
    run(["ffmpeg", "-y", "-i", str(clip), *sum((["-i", str(p)] for p in pngs), []),
         "-filter_complex", fc, "-map", "[v3]", "-t", f"{total:.2f}", *ENC, str(out)])
    return total


# ---------------------------------------------------------------- main
def match_episodes(log_path, clips):
    bodies = []
    for l in open(log_path, encoding="utf-8"):
        if l.strip():
            rec = json.loads(l)
            bodies.append(dict(rec["body"], _hash=rec["hash"]))
    # match by logged video name; tolerate renamed downloads such as "abc123-ep1_success_1.mp4"
    by_video = {pathlib.Path(b["video"]).stem: b for b in bodies if b.get("video")}   # later entries win
    matched = []
    for c in clips:
        name = pathlib.Path(c).stem
        hits = [stem for stem in by_video if stem in name]
        if not hits:
            break
        matched.append(by_video[max(hits, key=len)])
    else:
        return matched
    print("注意: 動画名でログと対応付けできないクリップがあるため、ログ末尾から順番に対応付ける")
    if len(bodies) < len(clips):
        sys.exit("ログのエピソード数がクリップ数より少ない")
    return bodies[-len(clips):]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--insert", action="append", default=[],
                    help="PNG:秒  エピソードの後に挿入する画像（マトリクス、CI画面など）")
    ap.add_argument("--account", default="<omnicampusアカウントID>")
    ap.add_argument("--font", default=None)
    ap.add_argument("--opening", default=None, help="講座提供のOP動画（任意）")
    ap.add_argument("--ending", default=None, help="講座提供のED動画（任意）")
    ap.add_argument("--out", default="draft.mp4")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg が見つかりません")

    if args.account.startswith("<"):
        print("警告: --account が未指定。タイトルカードに仮の文字列が出る（提出前に必ず指定）")
    bodies = match_episodes(args.log, args.clips)
    tmp = pathlib.Path(tempfile.mkdtemp())
    segs, total = [], 0.0
    f = args.font

    if args.opening:
        mp4 = tmp / "a00_opening.mp4"; total += normalize(args.opening, mp4); segs.append(mp4)

    def add_card(lines, sec, name):
        nonlocal total
        png, mp4 = tmp / f"{name}.png", tmp / f"{name}.mp4"
        card(lines, f, png); still_to_video(png, sec, mp4); segs.append(mp4); total += sec

    add_card([("Physical AI 応用1講座　最終課題", 30, MUTED),
              ("LLMを用いたロボット作業計画における", 50, FG),
              ("検証証跡の自動生成", 50, FG),
              (f"{args.account}　｜　Genesis / Franka Emika Panda / Claude　｜　等倍速", 26, MUTED)], 5, "c00_title")
    add_card([("背景と目的", 30, ACCENT),
              ("LLMの出力は、同一の指示に対しても一定しない。", 38, FG),
              ("このため、出力そのものを検証の対象とすることは難しい。", 38, FG),
              ("本課題では、LLMが作成した計画を実行前に規則ベースのゲートで検査し、", 28, MUTED),
              ("その検証結果を要求単位の証跡として、コミットごとに自動生成する。", 28, MUTED)],
             9, "c01_problem")
    add_card([("システム構成", 30, ACCENT),
              ("指示 → LLM（JSON形式の計画）→ 安全ゲート → 実行 → 判定", 38, FG),
              ("・ゲートは規則に基づいて判定し、違反には要求ID（REQ-SAF-xxx）を付す", 28, MUTED),
              ("・全実行をハッシュチェーン付きのログに記録する（字幕右上の「記録」）", 28, MUTED),
              ("・要求・テスト・結果の対応表（トレーサビリティマトリクス）をCIで生成する", 28, MUTED)],
             9, "c02_arch")

    for i, (clip, body) in enumerate(zip(args.clips, bodies), 1):
        out = tmp / f"e{i:02d}.mp4"
        total += caption_clip(pathlib.Path(clip), overlay_layers(i, body, f), out, tmp)
        segs.append(out)

    for j, spec in enumerate(args.insert):
        src, sec = spec.rsplit(":", 1)
        png, mp4 = tmp / f"i{j:02d}.png", tmp / f"i{j:02d}.mp4"
        image_slide(src, png); still_to_video(png, float(sec), mp4); segs.append(mp4); total += float(sec)

    add_card([("結果と課題", 30, ACCENT),
              ("安全要求4件と記録要求1件は、単体テスト・試行とも全件合格（PASS）。", 32, FG),
              ("ゲートの規則を1つ削除すると該当要求がFAILとなり、変更を検出できた。", 32, FG),
              ("機能・頑健性の要求3件は、試行数が基準に満たず判定保留とした。", 32, FG),
              ("課題：ゲートが検査できるのは、計画に現れる情報に限られる。", 26, MUTED),
              ("今後：LLMを含む試行を増やし、統計的な要求の判定を確定させる。", 26, MUTED)],
             10, "c99_summary")

    if args.ending:
        mp4 = tmp / "z99_ending.mp4"; total += normalize(args.ending, mp4); segs.append(mp4)

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", args.out])
    print(f"{args.out}: {duration(args.out):.1f} s  ({len(segs)} segments)")
    if not 60 <= duration(args.out) <= 180:
        print("注意: 提出要件は 1〜3 分。--insert で画像を足すか、カードの秒数を調整すること")


if __name__ == "__main__":
    main()

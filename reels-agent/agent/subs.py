"""ASS (libass) tekst za segment: animirani tekst na ekranu + automatski titlovi (karaoke, rec-po-rec, klasicni)."""
from __future__ import annotations

import textwrap

W, H = 1080, 1920

# &HAABBGGRR
WHITE, BLACK, YELLOW, PINK = "&H00FFFFFF", "&H00000000", "&H0000D4FF", "&H006E3DFF"


def header(font_name: str) -> str:
    def style(name, size, primary, outline, back, border_style, outline_w, shadow, align=5):
        return (f"Style: {name},{font_name},{size},{primary},{primary},{outline},{back},-1,0,0,0,100,100,0,0,"
                f"{border_style},{outline_w},{shadow},{align},60,60,60,1")
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        style("bold_white", 82, WHITE, BLACK, "&H80000000", 1, 6, 2),
        style("bold_yellow", 82, YELLOW, BLACK, "&H80000000", 1, 6, 2),
        style("boxed_black", 72, WHITE, "&H30000000", "&H30000000", 3, 18, 0),
        style("boxed_white", 72, BLACK, "&H10FFFFFF", "&H10FFFFFF", 3, 18, 0),
        style("caption", 76, WHITE, BLACK, "&H80000000", 1, 7, 3),
        style("caption_big", 104, WHITE, BLACK, "&H80000000", 1, 8, 3),
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]) + "\n"


def _ts(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(s: str) -> str:
    return s.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _event(start: float, end: float, style: str, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,0,0,0,,{text}\n"


Y_POS = {"top": int(H * 0.20), "center": H // 2, "bottom": int(H * 0.74)}


def overlay(text: str, position: str, style: str, animation: str, dur: float) -> str:
    text = _clean(text.strip())
    if not text:
        return ""
    lines = textwrap.wrap(text, width=18) or [text]
    x, y = W // 2, Y_POS.get(position, H // 2)
    base = f"\\an5\\pos({x},{y})"
    if animation == "pop":
        tags = base + "\\fscx30\\fscy30\\t(0,140,\\fscx112\\fscy112)\\t(140,240,\\fscx100\\fscy100)"
    elif animation == "fade":
        tags = base + "\\fad(250,150)"
    elif animation == "slide_up":
        tags = f"\\an5\\move({x},{y + 140},{x},{y},0,260)\\fad(180,0)"
    elif animation == "typewriter":
        full = "\\N".join(lines)
        chars = [c for c in full]
        step = min(60, int(max(dur * 0.5, 0.3) * 1000 / max(len(chars), 1)))
        out, t, i = [], 0, 0
        while i < len(chars):
            if full[i:i + 2] == "\\N":
                out.append("\\N")
                i += 2
                continue
            out.append(f"{{\\alpha&HFF&\\t({t},{t + 1},\\alpha&H00&)}}{chars[i]}")
            t += step
            i += 1
        return _event(0, dur, style, "{" + base + "}" + "".join(out), layer=2)
    else:
        tags = base
    return _event(0, dur, style, "{" + tags + "}" + "\\N".join(lines), layer=2)


def _chunks(words: list[dict], max_words: int = 3, max_chars: int = 22) -> list[list[dict]]:
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > 0.6
                    or sum(len(x["w"]) + 1 for x in cur) + len(w["w"]) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def captions(words: list[dict], style: str, position: str, dur: float) -> str:
    if not words or style == "none":
        return ""
    y = Y_POS.get(position, Y_POS["bottom"])
    pos = f"\\an5\\pos({W // 2},{y})"
    ev = []
    if style == "word_pop":
        for i, w in enumerate(words):
            end = words[i + 1]["start"] if i + 1 < len(words) else min(w["end"] + 0.3, dur)
            end = max(end, w["start"] + 0.12)
            txt = _clean(w["w"]).upper()
            ev.append(_event(w["start"], min(end, dur), "caption_big",
                             "{" + pos + "\\fscx60\\fscy60\\t(0,110,\\fscx108\\fscy108)\\t(110,180,\\fscx100\\fscy100)}" + txt, 1))
        return "".join(ev)
    for chunk in _chunks(words):
        c_start = chunk[0]["start"]
        c_end = min(max(chunk[-1]["end"] + 0.15, c_start + 0.3), dur)
        if style == "classic":
            ev.append(_event(c_start, c_end, "caption", "{" + pos + "}" + " ".join(_clean(w["w"]) for w in chunk), 1))
            continue
        # karaoke: cela fraza vidljiva, aktivna rec zuta i malo veca
        for i, w in enumerate(chunk):
            w_start = c_start if i == 0 else w["start"]
            w_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else c_end
            if w_end <= w_start:
                continue
            parts = []
            for j, x in enumerate(chunk):
                t = _clean(x["w"]).upper()
                parts.append(f"{{\\c{YELLOW}\\fscx112\\fscy112}}{t}{{\\c{WHITE}\\fscx100\\fscy100}}" if j == i else t)
            ev.append(_event(w_start, min(w_end, dur), "caption", "{" + pos + "}" + " ".join(parts), 1))
    return "".join(ev)

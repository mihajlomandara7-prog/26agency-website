"""Renderovanje plana montaze u vertikalni 1080x1920 reel pomocu ffmpeg-a."""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Callable

W, H, FPS = 1080, 1920, 30

GRADE_FILTERS = {
    "none": "",
    "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.05:bm=-0.05,eq=saturation=1.1",
    "cool": "colorbalance=rs=-0.06:bs=0.08:rm=-0.04:bm=0.06,eq=saturation=1.05",
    "high_contrast": "eq=contrast=1.25:saturation=1.15:brightness=-0.02",
    "vintage": "curves=preset=vintage,eq=saturation=0.85",
    "black_white": "hue=s=0,eq=contrast=1.15",
    "vibrant": "eq=saturation=1.4:contrast=1.08",
    "moody": "eq=contrast=1.15:brightness=-0.05:saturation=0.8,colorbalance=bs=0.05:bm=0.03",
}

FONT_CANDIDATES = [
    os.environ.get("REELS_AGENT_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font() -> str | None:
    return next((f for f in FONT_CANDIDATES if f and Path(f).exists()), None)


def _esc(path: str) -> str:
    # escape za putanje unutar ffmpeg filter grafa
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _text_filters(seg: dict, tmp: Path, i: int) -> list[str]:
    text = seg["text"].strip()
    font = _font()
    if not text or not font:
        return []
    lines = textwrap.wrap(text, width=18) or [text]
    size = 78 if len(lines) <= 2 else 64
    line_h = int(size * 1.25)
    block = line_h * len(lines)
    top = {"top": int(H * 0.16), "center": (H - block) // 2, "bottom": int(H * 0.70)}[seg["text_position"]]
    style = {
        "bold_white": "fontcolor=white:borderw=6:bordercolor=black",
        "bold_yellow": "fontcolor=#FFD400:borderw=6:bordercolor=black",
        "boxed_black": "fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=18",
        "boxed_white": "fontcolor=black:box=1:boxcolor=white@0.92:boxborderw=18",
    }[seg["text_style"]]
    out = []
    for j, line in enumerate(lines):
        tf = tmp / f"text_{i:03d}_{j}.txt"
        tf.write_text(line, encoding="utf-8")
        out.append(
            f"drawtext=fontfile='{_esc(font)}':textfile='{_esc(str(tf))}':fontsize={size}:{style}"
            f":x=(w-text_w)/2:y={top + j * line_h}"
        )
    return out


def _video_chain(seg: dict, grade: str, tmp: Path, i: int) -> str:
    dur = seg["duration"]
    frames = max(int(dur * FPS), 1)
    f = [f"setpts=(PTS-STARTPTS)/{seg['speed']}", f"fps={FPS}"]
    if seg["effect"] == "shake":
        f += [f"scale={int(W*1.08)}:{int(H*1.08)}:force_original_aspect_ratio=increase",
              f"crop={W}:{H}:x='(iw-ow)/2+sin(t*38)*14':y='(ih-oh)/2+cos(t*31)*14'"]
    else:
        f += [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}"]
        if seg["effect"] in ("zoom_in", "zoom_out"):
            z = f"1+0.15*on/{frames}" if seg["effect"] == "zoom_in" else f"1.15-0.15*on/{frames}"
            f.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}")
    if GRADE_FILTERS.get(grade):
        f.append(GRADE_FILTERS[grade])
    if seg["transition_in"] == "flash":
        f.append("fade=t=in:st=0:d=0.18:color=white")
    elif seg["transition_in"] == "fade":
        f.append("fade=t=in:st=0:d=0.35")
    f += _text_filters(seg, tmp, i)
    f += ["setsar=1", "format=yuv420p"]
    return ",".join(f)


def _atempo(speed: float) -> str:
    return f"atempo={speed}" if abs(speed - 1.0) > 1e-3 else "anull"


def render_segment(seg: dict, clip: dict, grade: str, out: Path, tmp: Path, i: int, keep_audio: bool) -> None:
    src_len = seg["duration"] * seg["speed"]
    vchain = _video_chain(seg, grade, tmp, i)
    use_clip_audio = keep_audio and clip["has_audio"]
    achain = (f"[0:a]{_atempo(seg['speed'])},aresample=44100,aformat=channel_layouts=stereo[a]"
              if use_clip_audio else "[1:a]anull[a]")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seg['source_start']:.3f}", "-t", f"{src_len + 0.1:.3f}", "-i", clip["file"],
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", f"[0:v]{vchain}[v];{achain}",
        "-map", "[v]", "-map", "[a]", "-t", f"{seg['duration']:.3f}",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Render segmenta {i} nije uspeo: {res.stderr.strip()[-600:]}")


def render_plan(plan: dict, clips: list[dict], out: Path, workdir: Path, audio_mode: str = "reference_music",
                reference: Path | None = None, music: Path | None = None,
                progress: Callable[[str], None] = lambda s: None) -> Path:
    tmp = workdir / "render_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*"):
        old.unlink()
    by_idx = {c["index"]: c for c in clips}
    keep_audio = audio_mode == "clip_audio"
    parts = []
    segs = plan["segments"]
    for i, seg in enumerate(segs):
        progress(f"Renderujem segment {i + 1}/{len(segs)}")
        part = tmp / f"seg_{i:03d}.mp4"
        render_segment(seg, by_idx[seg["clip_index"]], plan.get("color_grade", "none"), part, tmp, i, keep_audio)
        parts.append(part)

    progress("Spajam segmente")
    listfile = tmp / "list.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    body = tmp / "body.mp4"
    res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                          "-i", str(listfile), "-c", "copy", str(body)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Spajanje nije uspelo: {res.stderr.strip()[-600:]}")

    track = music if audio_mode == "uploaded_music" else reference if audio_mode == "reference_music" else None
    if track is None:
        body.replace(out)
        return out

    progress("Dodajem muziku")
    total = sum(s["duration"] for s in segs)
    fade_st = max(total - 0.8, 0)
    res = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(body), "-i", str(track),
        "-filter_complex", f"[1:a]atrim=0:{total:.3f},apad,afade=t=out:st={fade_st:.3f}:d=0.8,aresample=44100[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
        "-movflags", "+faststart", str(out),
    ], capture_output=True, text=True)
    if res.returncode != 0:  # npr. referenca nema zvuk -> zadrzi bez muzike
        body.replace(out)
    return out

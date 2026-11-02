"""Renderovanje plana montaze u vertikalni 1080x1920 reel pomocu ffmpeg-a.

Svaki segment se renderuje posebno (kadriranje, brzina, efekti, kolor, animirani tekst i titlovi preko libass),
pa se segmenti spajaju jednim filter grafom: obicni rez = concat, a swipe/whip/zoom/... = xfade.
Da rezovi ostanu na udarcima muzike, segment ispred xfade tranzicije dobija "rep" (tail) koji se preklapa.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from . import subs, transcribe

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

# tranzicije koje se desavaju unutar segmenta (na njegovom pocetku)
IN_SEGMENT = {"cut", "flash", "fade", "glitch", "zoom_punch"}
# tranzicije koje preklapaju dva segmenta (ffmpeg xfade)
XFADE = {
    "swipe_left": ("slideleft", 0.30),
    "swipe_up": ("slideup", 0.30),
    "whip": ("hblur", 0.25),
    "crossfade": ("fade", 0.40),
    "zoom": ("zoomin", 0.35),
    "circle": ("circleopen", 0.40),
    "pixelize": ("pixelize", 0.35),
    "dip_white": ("fadewhite", 0.40),
}

FONT_CANDIDATES = [
    os.environ.get("REELS_AGENT_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font() -> tuple[str, str] | None:
    """(putanja, ime familije) fonta za libass."""
    path = next((f for f in FONT_CANDIDATES if f and Path(f).exists()), None)
    if not path:
        return None
    try:
        from PIL import ImageFont
        family = ImageFont.truetype(path, 20).getname()[0]
    except Exception:  # noqa: BLE001
        family = Path(path).stem.replace("-Bold", "").replace("bd", "")
    return path, family


def _esc(path: str) -> str:
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _ass_filter(seg: dict, words: list[dict], captions: dict, tmp: Path, i: int, dur: float) -> str:
    font = _font()
    body = subs.overlay(seg["text"], seg["text_position"], seg["text_style"], seg.get("text_animation", "none"), dur)
    body += subs.captions(words, captions.get("style", "none"), captions.get("position", "bottom"), dur)
    if not body:
        return ""
    assf = tmp / f"seg_{i:03d}.ass"
    assf.write_text(subs.header(font[1] if font else "Arial") + body, encoding="utf-8")
    f = f"ass=filename='{_esc(str(assf))}'"
    if font:
        f += f":fontsdir='{_esc(str(Path(font[0]).parent))}'"
    return f


def _video_chain(seg: dict, grade: str, total: float, ass: str) -> str:
    frames = max(int(total * FPS), 1)
    f = [f"setpts=(PTS-STARTPTS)/{seg['speed']}", f"fps={FPS}"]
    if seg["effect"] == "shake":
        f += [f"scale={int(W*1.08)}:{int(H*1.08)}:force_original_aspect_ratio=increase",
              f"crop={W}:{H}:x='(iw-ow)/2+sin(t*38)*14':y='(ih-oh)/2+cos(t*31)*14'"]
    else:
        f += [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}"]
    z = {"zoom_in": f"(1+0.15*on/{frames})", "zoom_out": f"(1.15-0.15*on/{frames})"}.get(seg["effect"], "1")
    if seg["transition_in"] == "zoom_punch":
        z += "*if(lt(on,7),1.3-0.3*on/7,1)"
    if z != "1":
        f.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}")
    if GRADE_FILTERS.get(grade):
        f.append(GRADE_FILTERS[grade])
    t = seg["transition_in"]
    if t == "flash":
        f.append("fade=t=in:st=0:d=0.18:color=white")
    elif t == "fade":
        f.append("fade=t=in:st=0:d=0.35")
    elif t == "glitch":
        g = "enable='lt(t,0.28)+between(t,0.45,0.52)'"
        f += [f"rgbashift=rh=-28:bh=28:gv=10:{g}", f"noise=alls=55:allf=t:{g}",
              f"hue=H=2*PI*t*3:{g}"]
    if ass:
        f.append(ass)
    f += ["setsar=1", "format=yuv420p"]
    return ",".join(f)


def _atempo(speed: float) -> str:
    return f"atempo={speed}" if abs(speed - 1.0) > 1e-3 else "anull"


def render_segment(seg: dict, clip: dict, grade: str, out: Path, tmp: Path, i: int, keep_audio: bool,
                   tail: float, words: list[dict], captions: dict) -> None:
    total = seg["duration"] + tail
    src_len = total * seg["speed"]
    ass = _ass_filter(seg, words, captions, tmp, i, seg["duration"])
    vchain = _video_chain(seg, grade, total, ass)
    use_clip_audio = keep_audio and clip["has_audio"]
    achain = (f"[0:a]{_atempo(seg['speed'])},aresample=44100,aformat=channel_layouts=stereo,apad[a]"
              if use_clip_audio else "[1:a]anull[a]")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seg['source_start']:.3f}", "-t", f"{src_len + 0.1:.3f}", "-i", clip["file"],
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", f"[0:v]{vchain}[v];{achain}",
        "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Render segmenta {i + 1} nije uspeo: {res.stderr.strip()[-600:]}")


def layout(segs: list[dict], clips_by_idx: dict) -> list[float]:
    """Racuna rep (tail) svakog segmenta; xfade koji nema dovoljno materijala postaje obican rez."""
    tails = [0.0] * len(segs)
    for i in range(len(segs) - 1):
        nxt = segs[i + 1]
        if nxt["transition_in"] not in XFADE:
            continue
        d = min(XFADE[nxt["transition_in"]][1], segs[i]["duration"] * 0.5, nxt["duration"] * 0.5)
        seg, clip = segs[i], clips_by_idx[segs[i]["clip_index"]]
        need = (seg["duration"] + d) * seg["speed"]
        if need > clip["duration"] - 0.02:
            nxt["transition_in"] = "cut"
            continue
        if seg["source_start"] + need > clip["duration"] - 0.02:
            seg["source_start"] = round(clip["duration"] - need - 0.02, 3)
        tails[i] = round(d, 3)
    return tails


def _assemble(parts: list[Path], segs: list[dict], tails: list[float], out: Path) -> None:
    n = len(parts)
    inputs = []
    for p in parts:
        inputs += ["-i", str(p)]
    # isti timebase/fps za sve ulaze (xfade to zahteva)
    graph = [f"[{i}:v]fps={FPS},format=yuv420p,setpts=PTS-STARTPTS,settb=AVTB[s{i}]" for i in range(n)]
    cur, offset = "[s0]", 0.0
    for i in range(1, n):
        offset += segs[i - 1]["duration"]
        label = f"[v{i}]"
        t = segs[i]["transition_in"]
        if t in XFADE and tails[i - 1] > 0:
            graph.append(f"{cur}[s{i}]xfade=transition={XFADE[t][0]}:duration={tails[i - 1]}"
                         f":offset={offset:.3f},settb=AVTB{label}")
        else:
            graph.append(f"{cur}[s{i}]concat=n=2:v=1:a=0,settb=AVTB{label}")
        cur = label
    total = sum(s["duration"] for s in segs)
    audio = "".join(f"[{i}:a]atrim=0:{segs[i]['duration']:.3f},asetpts=PTS-STARTPTS[a{i}];" for i in range(n))
    audio += "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    vout = cur
    graph_s = ";".join(graph + [audio])
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
           "-filter_complex", graph_s, "-map", vout, "-map", "[aout]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Spajanje nije uspelo: {res.stderr.strip()[-800:]}")


def render_plan(plan: dict, clips: list[dict], out: Path, workdir: Path, audio_mode: str = "reference_music",
                reference: Path | None = None, music: Path | None = None, transcripts: dict | None = None,
                progress: Callable[[str], None] = lambda s: None) -> Path:
    tmp = workdir / "render_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*"):
        old.unlink()
    by_idx = {c["index"]: c for c in clips}
    keep_audio = audio_mode in ("clip_audio", "clip_audio_music")
    captions = plan.get("captions") or {"style": "none", "position": "bottom"}
    transcripts = transcripts or {}
    segs = plan["segments"]
    tails = layout(segs, by_idx)
    parts = []
    for i, seg in enumerate(segs):
        progress(f"Renderujem segment {i + 1}/{len(segs)}")
        words = []
        tr = transcripts.get(str(seg["clip_index"]))
        if tr and captions.get("style", "none") != "none":
            src_end = seg["source_start"] + seg["duration"] * seg["speed"]
            words = transcribe.words_in_window(tr["words"], seg["source_start"], src_end, seg["speed"])
        part = tmp / f"seg_{i:03d}.mp4"
        render_segment(seg, by_idx[seg["clip_index"]], plan.get("color_grade", "none"), part, tmp, i,
                       keep_audio, tails[i], words, captions)
        parts.append(part)

    progress("Spajam segmente i tranzicije")
    body = tmp / "body.mp4"
    _assemble(parts, segs, tails, body)

    track = None
    if audio_mode in ("uploaded_music", "reference_music"):
        track = music if audio_mode == "uploaded_music" else reference
    elif audio_mode == "clip_audio_music":
        track = music or reference
    if track is None:
        body.replace(out)
        return out

    progress("Dodajem muziku")
    total = sum(s["duration"] for s in segs)
    fade_st = max(total - 0.8, 0)
    music_chain = f"[1:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,apad,afade=t=out:st={fade_st:.3f}:d=0.8,aresample=44100"
    if audio_mode == "clip_audio_music":
        # govor u prvom planu, muzika tiho ispod (ducking preko sidechain kompresora)
        graph = (f"{music_chain},volume=0.35[m];[0:a]asplit=2[v1][v2];"
                 f"[m][v2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[md];"
                 f"[v1][md]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        graph = music_chain + "[a]"
    res = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(body), "-i", str(track),
        "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{total:.3f}", "-movflags", "+faststart", str(out),
    ], capture_output=True, text=True)
    if res.returncode != 0:  # npr. referenca nema zvuk -> zadrzi bez muzike
        body.replace(out)
    return out

"""Analiza videa pomocu ffmpeg/ffprobe: rezovi (scene cuts), ritam muzike, kljucni frejmovi."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=kw.pop("text", True), check=False, **kw)


def probe(path: Path) -> dict:
    res = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe nije uspeo za {path.name}: {res.stderr.strip()[:300]}")
    data = json.loads(res.stdout)
    v = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
    duration = float(data["format"].get("duration") or (v or {}).get("duration") or 0)
    info = {"duration": round(duration, 3), "has_audio": a is not None, "has_video": v is not None}
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) in (90, 270):
            w, h = h, w
        num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
        info.update(width=w, height=h, fps=round(fps, 2))
    return info


def detect_cuts(path: Path, threshold: float = 0.3) -> list[float]:
    """Vraca vremena (s) na kojima se desava rez u videu."""
    res = run([
        "ffmpeg", "-hide_banner", "-i", str(path), "-an",
        "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-",
    ])
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", res.stderr)]
    cuts: list[float] = []
    for t in times:  # izbaci rezove blize od 0.2s (flash/glitch efekti)
        if not cuts or t - cuts[-1] > 0.2:
            cuts.append(round(t, 3))
    return cuts


def detect_beats(path: Path, sr: int = 22050) -> dict:
    """Jednostavna detekcija udaraca (onset) i BPM-a iz audio trake."""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True, check=False,
    )
    samples = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size < sr:  # manje od sekunde zvuka
        return {"bpm": None, "beats": []}
    hop, win = 512, 1024
    n = 1 + (samples.size - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = samples[idx] * np.hanning(win)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0.0, np.diff(np.log1p(spec * 10), axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    if flux.max() <= 0:
        return {"bpm": None, "beats": []}
    flux /= flux.max()
    fps = sr / hop

    # BPM preko autokorelacije onset krive (60-180 BPM)
    env = flux - flux.mean()
    ac = np.correlate(env, env, mode="full")[env.size - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    bpm = None
    if hi < ac.size:
        lag = lo + int(np.argmax(ac[lo:hi]))
        bpm = round(60.0 * fps / lag, 1)

    # Pikovi: lokalni maksimumi iznad praga, min razmak 0.25s
    thr = flux.mean() + flux.std()
    min_gap = int(0.25 * fps)
    beats: list[float] = []
    last = -min_gap
    for i in range(1, flux.size - 1):
        if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and i - last >= min_gap:
            beats.append(round(i / fps, 3))
            last = i
    return {"bpm": bpm, "beats": beats}


def extract_frame(path: Path, t: float, out: Path, width: int = 480) -> Path:
    res = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(path),
               "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(f"Ne mogu da izvucem frejm iz {path.name} na {t:.2f}s")
    return out


def analyze_reference(path: Path, workdir: Path, max_frames: int = 16) -> dict:
    info = probe(path)
    dur = info["duration"]
    cuts = [c for c in detect_cuts(path) if 0.1 < c < dur - 0.1]
    if not cuts and dur > 3:  # mekani rezovi / slicni kadrovi -> probaj osetljiviji prag
        cuts = [c for c in detect_cuts(path, threshold=0.18) if 0.1 < c < dur - 0.1]
    bounds = [0.0, *cuts, dur]
    shots = [
        {"index": i, "start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3)}
        for i, (s, e) in enumerate(zip(bounds, bounds[1:])) if e - s > 0.05
    ]
    frames_dir = workdir / "ref_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Ako ima previse kadrova, uzmi ravnomeran uzorak za vizuelnu analizu
    step = max(1, int(np.ceil(len(shots) / max_frames)))
    for shot in shots[::step]:
        mid = shot["start"] + shot["duration"] / 2
        shot["frame"] = str(extract_frame(path, mid, frames_dir / f"shot_{shot['index']:03d}.jpg"))
        if shot["duration"] > 0.6:  # frejm odmah posle reza: vidi se animacija teksta / tranzicija
            early = shot["start"] + min(0.15, shot["duration"] * 0.2)
            shot["frame_start"] = str(extract_frame(path, early, frames_dir / f"shot_{shot['index']:03d}_a.jpg"))
    beats = detect_beats(path) if info["has_audio"] else {"bpm": None, "beats": []}
    return {**info, "shots": shots, "bpm": beats["bpm"], "beats": beats["beats"]}


def analyze_clip(path: Path, workdir: Path, idx: int) -> dict:
    info = probe(path)
    if not info["has_video"]:
        raise RuntimeError(f"{path.name} nema video traku")
    frames_dir = workdir / "clip_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    dur = info["duration"]
    points = [0.1, 0.5, 0.9] if dur > 1.5 else [0.5]
    frames = []
    for p in points:
        t = dur * p
        frames.append({"t": round(t, 2), "path": str(extract_frame(path, t, frames_dir / f"clip{idx:02d}_{int(p*100)}.jpg"))})
    return {**info, "index": idx, "file": str(path), "name": path.name, "frames": frames}


IMAGE_CODECS = {"mjpeg", "png", "webp", "bmp", "tiff", "gif", "heif", "hevc_image", "jpegxl", "avif"}


def media_kind(path: Path) -> str | None:
    """Prepoznaje sadrzaj fajla bez obzira na ekstenziju: "video", "image", "audio" ili None."""
    res = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if res.returncode != 0:
        return None
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {}).get("format_name", "")
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v:
        dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
        still = fmt.startswith("image2") or fmt.endswith("_pipe") or (
            v.get("codec_name") in IMAGE_CODECS and dur < 0.1)
        if still:
            return "image"
        if v.get("disposition", {}).get("attached_pic") and a:
            return "audio"  # mp3 sa omotom albuma
        return "video"
    return "audio" if a else None


def image_to_clip(path: Path, out: Path, seconds: float = 6.0) -> Path:
    """Slika -> vertikalni 1080x1920 video; ako slika nije vertikalna, pozadina je zamucena verzija slike."""
    vf = ("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=30:2,eq=brightness=-0.08[bg];[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
          "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p")
    res = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(path),
               "-t", f"{seconds}", "-r", "30", "-filter_complex", vf, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", str(out)])
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(f"Ne mogu da pretvorim sliku {path.name} u video: {res.stderr.strip()[-300:]}")
    return out

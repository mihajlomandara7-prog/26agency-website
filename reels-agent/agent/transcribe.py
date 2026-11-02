"""Prepoznavanje govora (faster-whisper, lokalno) sa vremenom za svaku rec - za automatske titlove."""
from __future__ import annotations

import json
import os
from pathlib import Path

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Za titlove instaliraj faster-whisper: pip install faster-whisper") from e
        name = os.environ.get("REELS_AGENT_WHISPER_MODEL", "small")
        _model = WhisperModel(name, device=os.environ.get("REELS_AGENT_WHISPER_DEVICE", "auto"),
                              compute_type=os.environ.get("REELS_AGENT_WHISPER_COMPUTE", "int8"))
    return _model


def transcribe(path: Path, cache: Path, language: str | None = None) -> dict:
    """Vraca {"language": "sr", "words": [{"w": "Zdravo", "start": 0.12, "end": 0.48}, ...]}."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    segments, info = _get_model().transcribe(
        str(path), language=language or os.environ.get("REELS_AGENT_LANGUAGE") or None,
        word_timestamps=True, vad_filter=True,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "start": round(w.start, 3), "end": round(w.end, 3)})
    result = {"language": info.language, "words": words}
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def words_in_window(words: list[dict], start: float, end: float, speed: float) -> list[dict]:
    """Reci iz [start, end) izvornog klipa, prebacene u vreme segmenta (pocinje od 0, uz brzinu)."""
    out = []
    for w in words:
        if start <= w["start"] < end:
            out.append({"w": w["w"], "start": (w["start"] - start) / speed,
                        "end": (min(w["end"], end) - start) / speed})
    return out


def transcript_text(words: list[dict], max_chars: int = 1500) -> str:
    """Kompaktan prikaz za Claude-a: recenice sa vremenima, npr. "[1.2s] Zdravo svima ..."."""
    lines, cur, cur_start, last_end = [], [], None, 0.0
    for w in words:
        if cur and (w["start"] - last_end > 0.7 or len(cur) >= 12):
            lines.append(f"[{cur_start:.1f}-{last_end:.1f}s] {' '.join(cur)}")
            cur = []
        if not cur:
            cur_start = w["start"]
        cur.append(w["w"])
        last_end = w["end"]
    if cur:
        lines.append(f"[{cur_start:.1f}-{last_end:.1f}s] {' '.join(cur)}")
    text = "\n".join(lines)
    return text[:max_chars] + (" ..." if len(text) > max_chars else "")

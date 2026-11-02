"""Agent pipeline: analiza -> plan (Claude) -> render. Jobovi se cuvaju na disku (data/jobs/<id>)."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import analyze, planner, render, transcribe

DATA = Path(__file__).resolve().parent.parent / "data" / "jobs"
_lock = threading.Lock()


class Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = DATA / job_id
        self.file = self.dir / "job.json"

    @classmethod
    def create(cls) -> "Job":
        job = cls(uuid.uuid4().hex[:12])
        (job.dir / "input").mkdir(parents=True, exist_ok=True)
        job.save(status="created", step="", log=[], version=0, created=time.time())
        return job

    def load(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))

    def save(self, **fields) -> dict:
        with _lock:
            data = self.load() if self.file.exists() else {"id": self.id}
            data.update(fields)
            self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data

    def step(self, msg: str) -> None:
        with _lock:
            data = self.load()
            data["step"] = msg
            data.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {msg}")
            self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _transcripts(job: Job) -> dict:
    f = job.dir / "transcripts.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _apply_caption_choice(plan: dict, data: dict, transcripts: dict) -> dict:
    choice = data.get("captions", "auto")
    has_speech = any(t.get("words") for t in transcripts.values())
    if not has_speech or choice == "none":
        plan["captions"] = {**plan.get("captions", {}), "style": "none"}
    elif choice != "auto":
        plan["captions"] = {**plan.get("captions", {}), "style": choice}
    plan.setdefault("captions", {}).setdefault("position", "bottom")
    return plan


def _render(job: Job, data: dict, plan: dict) -> None:
    transcripts = _transcripts(job)
    plan = _apply_caption_choice(plan, data, transcripts)
    version = data.get("version", 0) + 1
    out = job.dir / f"reel_v{version}.mp4"
    render.render_plan(
        plan, data["clips"], out, job.dir, audio_mode=data["audio_mode"],
        reference=Path(data["reference"]), music=Path(data["music"]) if data.get("music") else None,
        transcripts=transcripts, progress=job.step,
    )
    job.save(status="done", step="Gotovo", plan=plan, version=version, video=out.name)


def _guard(job: Job, fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - prikazi gresku korisniku u UI
        job.step(f"GRESKA: {e}")
        job.save(status="error", error=str(e), trace=traceback.format_exc()[-2000:])


def run_new(job: Job) -> None:
    def work():
        data = job.save(status="running")
        job.step("Analiziram referentni video (rezovi, ritam, kadrovi)")
        ref = analyze.analyze_reference(Path(data["reference"]), job.dir)
        job.step(f"Referenca: {ref['duration']}s, {len(ref['shots'])} kadrova, BPM ~{ref['bpm']}")
        clips = []
        for i, path in enumerate(data["clip_files"]):
            job.step(f"Analiziram klip {i + 1}/{len(data['clip_files'])}")
            clips.append(analyze.analyze_clip(Path(path), job.dir, i))
            clips[-1]["is_photo"] = i in data.get("photo_clips", [])
        transcripts = _transcribe_all(job, data, ref, clips)
        data = job.save(ref=ref, clips=clips)
        job.step("Claude gleda referencu i tvoj materijal i pravi plan montaze...")
        plan = planner.make_plan(ref, clips, data.get("instructions", ""), transcripts)
        job.save(plan=plan)
        job.step(f"Plan: {len(plan['segments'])} segmenata. {plan['style_summary']}")
        _render(job, data, plan)

    _guard(job, work)


def _wants_speech(data: dict) -> bool:
    return data.get("captions", "auto") != "none" and (
        data["audio_mode"] in ("clip_audio", "clip_audio_music") or data.get("captions", "auto") != "auto")


def _transcribe_all(job: Job, data: dict, ref: dict, clips: list[dict]) -> dict:
    """Transkribuje govor iz klipova (i reference) ako trebaju titlovi. Greska ovde ne obara ceo job."""
    if not _wants_speech(data):
        return {}
    out: dict = {}
    tdir = job.dir / "transcripts"
    tdir.mkdir(exist_ok=True)
    try:
        for c in clips:
            if c["has_audio"]:
                job.step(f"Prepoznajem govor u klipu {c['index'] + 1} (Whisper)")
                out[str(c["index"])] = transcribe.transcribe(Path(c["file"]), tdir / f"clip{c['index']:02d}.json",
                                                             data.get("language") or None)
        if ref.get("has_audio"):
            job.step("Prepoznajem govor u referenci")
            ref["transcript"] = transcribe.transcribe(Path(data["reference"]), tdir / "reference.json",
                                                      data.get("language") or None)
    except Exception as e:  # noqa: BLE001
        job.step(f"UPOZORENJE: titlovi preskoceni - {e}")
        return {}
    (job.dir / "transcripts.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    words = sum(len(t["words"]) for t in out.values())
    job.step(f"Govor: {words} reci u klipovima")
    return out


def run_revise(job: Job, feedback: str) -> None:
    def work():
        data = job.save(status="running", error=None)
        job.step(f"Menjam plan po tvom komentaru: {feedback}")
        plan = planner.revise_plan(data["ref"], data["clips"], data["plan"], feedback, data.get("instructions", ""),
                                   _transcripts(job))
        job.save(plan=plan)
        _render(job, data, plan)

    _guard(job, work)


def run_rerender(job: Job, plan: dict) -> None:
    def work():
        data = job.save(status="running", error=None)
        job.step("Renderujem rucno izmenjen plan")
        _render(job, data, planner.sanitize(plan, data["clips"]))

    _guard(job, work)


def start(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()

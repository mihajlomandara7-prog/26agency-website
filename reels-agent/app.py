"""Web app za Reels agenta. Pokretanje:  python app.py   ->  http://127.0.0.1:8000"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import pipeline

app = FastAPI(title="Reels Agent")
STATIC = Path(__file__).parent / "static"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg"} | VIDEO_EXT


def _safe(name: str) -> str:
    stem, ext = os.path.splitext(Path(name or "file").name)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:60] + ext.lower()


def _store(upload: UploadFile, dest: Path, allowed: set[str]) -> Path:
    if Path(upload.filename or "").suffix.lower() not in allowed:
        raise HTTPException(400, f"Nepodrzan format: {upload.filename}")
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


def _job(job_id: str) -> pipeline.Job:
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise HTTPException(404)
    job = pipeline.Job(job_id)
    if not job.file.exists():
        raise HTTPException(404, "Job ne postoji")
    return job


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/jobs")
def create_job(
    reference: UploadFile = File(...),
    clips: list[UploadFile] = File(...),
    music: UploadFile | None = File(None),
    instructions: str = Form(""),
    audio_mode: str = Form("reference_music"),
    captions: str = Form("auto"),
    language: str = Form(""),
):
    if audio_mode not in ("reference_music", "uploaded_music", "clip_audio", "clip_audio_music"):
        raise HTTPException(400, "Nepoznat audio_mode")
    if captions not in ("auto", "none", "karaoke", "word_pop", "classic"):
        raise HTTPException(400, "Nepoznat stil titlova")
    if language and not re.fullmatch(r"[a-z]{2}", language):
        raise HTTPException(400, "Jezik mora biti kod od 2 slova, npr. sr")
    if not clips:
        raise HTTPException(400, "Dodaj bar jedan klip")
    if len(clips) > 20:
        raise HTTPException(400, "Maksimalno 20 klipova")
    job = pipeline.Job.create()
    inp = job.dir / "input"
    ref = _store(reference, inp / f"reference_{_safe(reference.filename)}", VIDEO_EXT)
    clip_files = [str(_store(c, inp / f"clip{i:02d}_{_safe(c.filename)}", VIDEO_EXT)) for i, c in enumerate(clips)]
    music_path = None
    if music is not None and music.filename:
        music_path = str(_store(music, inp / f"music_{_safe(music.filename)}", AUDIO_EXT))
    if audio_mode == "uploaded_music" and not music_path:
        raise HTTPException(400, "Izabrao si svoju muziku ali nisi uploadovao fajl")
    job.save(reference=str(ref), clip_files=clip_files, music=music_path,
             instructions=instructions, audio_mode=audio_mode, captions=captions, language=language)
    pipeline.start(pipeline.run_new, job)
    return {"id": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    data = _job(job_id).load()
    data.pop("trace", None)
    return data


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str):
    data = _job(job_id).load()
    if not data.get("video"):
        raise HTTPException(404, "Video jos nije spreman")
    return FileResponse(pipeline.DATA / job_id / data["video"], media_type="video/mp4",
                        filename=f"reel_{job_id}_v{data['version']}.mp4")


class Feedback(BaseModel):
    feedback: str


class PlanIn(BaseModel):
    plan: dict


def _ensure_idle(job: pipeline.Job) -> dict:
    data = job.load()
    if data["status"] == "running":
        raise HTTPException(409, "Agent jos radi na ovom videu")
    if not data.get("plan") or not data.get("clips"):
        raise HTTPException(409, "Nema plana za izmenu")
    return data


@app.post("/api/jobs/{job_id}/revise")
def revise(job_id: str, body: Feedback):
    job = _job(job_id)
    _ensure_idle(job)
    if not body.feedback.strip():
        raise HTTPException(400, "Napisi sta da promenim")
    job.save(status="running", error=None)
    pipeline.start(pipeline.run_revise, job, body.feedback.strip())
    return {"ok": True}


@app.post("/api/jobs/{job_id}/render")
def rerender(job_id: str, body: PlanIn):
    job = _job(job_id)
    _ensure_idle(job)
    job.save(status="running", error=None)
    pipeline.start(pipeline.run_rerender, job, body.plan)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))

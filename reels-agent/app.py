"""Web app za Reels agenta. Pokretanje:  python app.py   ->  http://127.0.0.1:8000"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel


def _load_env(path: Path) -> None:
    """Ucitava KLJUC=vrednost iz .env fajla (bez dodatnih paketa). Postojece env varijable imaju prednost."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_env(Path(__file__).parent / ".env")

from agent import analyze, pipeline  # noqa: E402  (posle .env, da REELS_AGENT_* podesavanja vaze)

app = FastAPI(title="Reels Agent")
STATIC = Path(__file__).parent / "static"


def _safe(name: str) -> str:
    stem, ext = os.path.splitext(Path(name or "file").name)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:60] + ext.lower()


def _store(upload: UploadFile, dest: Path, allowed: set[str]) -> tuple[Path, str]:
    """Snima fajl i prepoznaje sta je po sadrzaju (ekstenzija nije bitna, npr. Instagram fajlovi bez .mp4)."""
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    kind = analyze.media_kind(dest)
    if kind not in allowed:
        names = {"video": "video", "image": "slika", "audio": "audio"}
        ocekivano = " ili ".join(names[k] for k in sorted(allowed))
        raise HTTPException(400, f"Fajl '{upload.filename}' nije {ocekivano}" +
                            (" (prepoznat kao: " + names[kind] + ")" if kind else " (nepoznat format)"))
    return dest, kind


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
    ref, _ = _store(reference, inp / f"reference_{_safe(reference.filename)}", {"video"})
    clip_files, photo_clips = [], []
    for i, c in enumerate(clips):
        path, kind = _store(c, inp / f"clip{i:02d}_{_safe(c.filename)}", {"video", "image"})
        if kind == "image":
            try:
                path = analyze.image_to_clip(path, path.with_name(path.stem + "_photo.mp4"))
            except RuntimeError as e:
                raise HTTPException(400, str(e)) from e
            photo_clips.append(i)
        clip_files.append(str(path))
    music_path = None
    if music is not None and music.filename:
        music_path = str(_store(music, inp / f"music_{_safe(music.filename)}", {"audio", "video"})[0])
    if audio_mode == "uploaded_music" and not music_path:
        raise HTTPException(400, "Izabrao si svoju muziku ali nisi uploadovao fajl")
    job.save(reference=str(ref), clip_files=clip_files, photo_clips=photo_clips, music=music_path,
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


@app.get("/api/health")
def health():
    return {"api_key": bool(os.environ.get("ANTHROPIC_API_KEY")), "ffmpeg": bool(shutil.which("ffmpeg"))}


if __name__ == "__main__":
    import uvicorn

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n[!] ANTHROPIC_API_KEY nije podesen. Napravi fajl reels-agent/.env sa linijom:\n"
              "    ANTHROPIC_API_KEY=sk-ant-...\n    (pogledaj .env.example)\n")
    if not shutil.which("ffmpeg"):
        print("[!] ffmpeg nije instaliran ili nije u PATH-u.\n")

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))

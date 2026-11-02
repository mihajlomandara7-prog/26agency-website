"""Claude gleda referentni reel i tvoje klipove i pravi plan montaze (edit decision list)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import anthropic

from .transcribe import transcript_text

MODEL = os.environ.get("REELS_AGENT_MODEL", "claude-opus-5-5")

EFFECTS = ["none", "zoom_in", "zoom_out", "shake"]
TRANSITIONS = ["cut", "flash", "fade", "glitch", "zoom_punch", "swipe_left", "swipe_up", "whip", "crossfade",
               "zoom", "circle", "pixelize", "dip_white"]
TEXT_ANIMATIONS = ["none", "pop", "fade", "slide_up", "typewriter"]
CAPTION_STYLES = ["none", "karaoke", "word_pop", "classic"]
GRADES = ["none", "warm", "cool", "high_contrast", "vintage", "black_white", "vibrant", "moody"]
TEXT_POS = ["top", "center", "bottom"]
TEXT_STYLES = ["bold_white", "bold_yellow", "boxed_black", "boxed_white"]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "style_summary": {"type": "string", "description": "Kratak opis stila referentnog reela (tempo, vibe, tekst, boje)."},
        "clip_notes": {
            "type": "array",
            "description": "Za svaki korisnikov klip, redom po indeksu: sta se vidi u njemu.",
            "items": {"type": "string"},
        },
        "color_grade": {"type": "string", "enum": GRADES},
        "captions": {
            "type": "object",
            "description": "Automatski titlovi iz govora u klipovima (samo ako klipovi imaju govor).",
            "properties": {
                "style": {"type": "string", "enum": CAPTION_STYLES},
                "position": {"type": "string", "enum": TEXT_POS},
            },
            "required": ["style", "position"],
            "additionalProperties": False,
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_index": {"type": "integer"},
                    "source_start": {"type": "number", "description": "Sekunda u izvornom klipu odakle krece segment."},
                    "duration": {"type": "number", "description": "Trajanje segmenta u FINALNOM videu (s)."},
                    "speed": {"type": "number", "description": "0.5-2.0; 1 = normalno."},
                    "effect": {"type": "string", "enum": EFFECTS},
                    "transition_in": {"type": "string", "enum": TRANSITIONS},
                    "text": {"type": "string", "description": "Tekst na ekranu tokom segmenta, ili prazan string."},
                    "text_position": {"type": "string", "enum": TEXT_POS},
                    "text_style": {"type": "string", "enum": TEXT_STYLES},
                    "text_animation": {"type": "string", "enum": TEXT_ANIMATIONS},
                    "reason": {"type": "string", "description": "Kratko: koji referentni kadar ovo imitira i zasto."},
                },
                "required": ["clip_index", "source_start", "duration", "speed", "effect", "transition_in",
                             "text", "text_position", "text_style", "text_animation", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["style_summary", "clip_notes", "color_grade", "captions", "segments"],
    "additionalProperties": False,
}

SYSTEM = """Ti si iskusan video editor za Instagram Reels / TikTok. Dobijas REFERENTNI reel (kao niz kadrova sa \
tacnim vremenima rezova i ritmom muzike) i KORISNIKOV materijal (klipove sa frejmovima). Tvoj posao je da napravis \
plan montaze tako da finalni video od korisnikovog materijala izgleda i "oseca se" kao referenca: isti tempo i \
ritam rezova, slicna struktura (hook na pocetku, build-up, payoff), slican stil teksta na ekranu, slicni efekti i \
kolor.

Pravila:
- Prati ritam reference: trajanja segmenata neka prate trajanja referentnih kadrova; rezovi neka padaju na udarce \
(beats) kad god je to moguce. Ukupno trajanje neka bude priblizno trajanju reference, osim ako korisnik trazi drugacije.
- Za svaki segment izaberi klip i deo klipa ciji sadrzaj najbolje odgovara ulozi tog kadra u referenci \
(npr. siroki kadar za uvod, detalj za udarac, lice za reakciju). Prvi kadar mora biti najjaci vizuelni hook.
- source_start + duration*speed ne sme preci duzinu klipa. Ne ponavljaj isti deo klipa ako ima drugog materijala.
- Ako referenca ima tekst na ekranu, napisi tekst u istom fazonu ali o korisnikovom sadrzaju (na jeziku koji \
korisnik koristi ili koji je u referenci). Ako reference nema tekst, ostavi text prazan.
- Tekst neka bude kratak (do ~40 karaktera po segmentu).
- Koristi samo efekte, tranzicije, animacije i kolor iz ponudjenih vrednosti, birajuci one najblize referenci.
- Tranzicije: cut (obican rez - najcesci u reelsovima), flash (beli blic), fade (iz crnog), glitch (RGB/noise \
glitch), zoom_punch (udarni zoom na rezu), swipe_left/swipe_up (slajd), whip (whip pan blur), crossfade, zoom, \
circle, pixelize, dip_white. Ne preteruj - koristi ih tamo gde ih ima i referenca, ili na udarcima/dropu.
- Animacije teksta: pop (iskoci), fade, slide_up, typewriter (slovo po slovo), none.
- Titlovi (captions): ako klipovi imaju govor (dat je transkript), izaberi stil titlova najblizi referenci \
(karaoke = fraza sa istaknutom aktivnom reci, word_pop = jedna velika rec po rec, classic = obicni). Ako nema \
govora, style = none. Kad ima titlova, tekst na ekranu stavljaj tako da se ne preklapa sa njima.
- Kod talking-head materijala biraj delove klipova gde je izgovorena cela misao (vidi vremena u transkriptu), \
ne seci usred reci.
- Uputstva korisnika imaju prednost nad referencom."""


def _img(path: str) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _call(content: list[dict]) -> dict:
    client = _client()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Model je odbio zahtev (refusal). Probaj sa drugim materijalom ili uputstvom.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Odgovor modela je presecen (max_tokens). Probaj sa kracim referentnim videom.")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Model nije vratio plan.")
    return json.loads(text)


def _reference_text(ref: dict) -> str:
    shots = [{k: s[k] for k in ("index", "start", "end", "duration")} for s in ref["shots"]]
    beats = ref["beats"][:200]
    return (
        f"REFERENTNI REEL: trajanje {ref['duration']}s, {ref.get('width')}x{ref.get('height')}, "
        f"{len(shots)} kadrova, BPM ~{ref['bpm']}.\n"
        + (f"Govor/voiceover u referenci:\n{transcript_text(ref['transcript']['words'])}\n"
           if ref.get("transcript", {}).get("words") else "")
        + f"Kadrovi (vremena rezova): {json.dumps(shots)}\n"
        f"Udarci u muzici (s): {json.dumps(beats)}\n"
    )


def _clips_text(clips: list[dict], transcripts: dict | None = None) -> str:
    rows = [{"clip_index": c["index"], "name": c["name"], "duration": c["duration"],
             "orientation": "vertical" if c.get("height", 0) > c.get("width", 0) else "horizontal",
             "has_audio": c["has_audio"]} for c in clips]
    text = f"KORISNIKOVI KLIPOVI: {json.dumps(rows, ensure_ascii=False)}\n"
    for idx, tr in sorted((transcripts or {}).items(), key=lambda kv: int(kv[0])):
        if tr.get("words"):
            text += f"\nGOVOR U KLIPU {idx} (jezik: {tr.get('language')}):\n{transcript_text(tr['words'])}\n"
    return text


def make_plan(ref: dict, clips: list[dict], instructions: str = "", transcripts: dict | None = None) -> dict:
    content: list[dict] = [{"type": "text", "text": _reference_text(ref) + "\nFrejmovi iz referentnih kadrova (sredina kadra):"}]
    for shot in ref["shots"]:
        if shot.get("frame"):
            content.append({"type": "text", "text": f"REF kadar {shot['index']} ({shot['start']}-{shot['end']}s):"})
            if shot.get("frame_start"):
                content.append({"type": "text", "text": "(odmah posle reza)"})
                content.append(_img(shot["frame_start"]))
                content.append({"type": "text", "text": "(sredina kadra)"})
            content.append(_img(shot["frame"]))
    content.append({"type": "text", "text": "\n" + _clips_text(clips, transcripts) + "Frejmovi iz korisnikovih klipova:"})
    per_clip = 3 if len(clips) <= 15 else 2
    for c in clips:
        for f in c["frames"][:per_clip]:
            content.append({"type": "text", "text": f"KLIP {c['index']} @ {f['t']}s:"})
            content.append(_img(f["path"]))
    content.append({"type": "text", "text": (
        f"\nUputstva korisnika: {instructions.strip() or '(nema - samo kopiraj stil reference)'}\n"
        "Napravi plan montaze."
    )})
    return sanitize(_call(content), clips)


def revise_plan(ref: dict, clips: list[dict], plan: dict, feedback: str, instructions: str = "",
                transcripts: dict | None = None) -> dict:
    notes = "\n".join(f"KLIP {i}: {n}" for i, n in enumerate(plan.get("clip_notes", [])))
    content = [{"type": "text", "text": (
        _reference_text(ref) + _clips_text(clips, transcripts) +
        f"Opis sadrzaja klipova (iz ranije analize):\n{notes}\n\n"
        f"Prvobitna uputstva korisnika: {instructions or '(nema)'}\n\n"
        f"TRENUTNI PLAN:\n{json.dumps(plan, ensure_ascii=False)}\n\n"
        f"Korisnik je pogledao video i trazi izmene:\n{feedback}\n\n"
        "Vrati kompletan izmenjen plan (zadrzi ono sto korisnik nije trazio da se menja)."
    )}]
    return sanitize(_call(content), clips)


def sanitize(plan: dict, clips: list[dict]) -> dict:
    """Ispravlja vrednosti van opsega da render nikad ne pukne zbog plana."""
    by_idx = {c["index"]: c for c in clips}
    fixed = []
    for seg in plan.get("segments", []):
        clip = by_idx.get(seg.get("clip_index"))
        if clip is None:
            continue
        speed = min(max(float(seg.get("speed") or 1.0), 0.5), 2.0)
        dur = min(max(float(seg.get("duration") or 1.0), 0.2), 30.0)
        src_len = dur * speed
        if src_len > clip["duration"]:
            dur = max(clip["duration"] / speed - 0.05, 0.2)
            src_len = dur * speed
        start = min(max(float(seg.get("source_start") or 0.0), 0.0), max(clip["duration"] - src_len - 0.02, 0.0))
        seg.update(speed=round(speed, 3), duration=round(dur, 3), source_start=round(start, 3))
        for key, allowed, default in (("effect", EFFECTS, "none"), ("transition_in", TRANSITIONS, "cut"),
                                      ("text_position", TEXT_POS, "center"), ("text_style", TEXT_STYLES, "bold_white"),
                                      ("text_animation", TEXT_ANIMATIONS, "none")):
            if seg.get(key) not in allowed:
                seg[key] = default
        seg["text"] = str(seg.get("text") or "")
        fixed.append(seg)
    if not fixed:
        raise RuntimeError("Plan nema validnih segmenata.")
    plan["segments"] = fixed
    if plan.get("color_grade") not in GRADES:
        plan["color_grade"] = "none"
    cap = plan.get("captions") if isinstance(plan.get("captions"), dict) else {}
    plan["captions"] = {"style": cap.get("style") if cap.get("style") in CAPTION_STYLES else "none",
                        "position": cap.get("position") if cap.get("position") in TEXT_POS else "bottom"}
    return plan

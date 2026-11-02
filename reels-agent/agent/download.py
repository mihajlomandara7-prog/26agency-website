"""Preuzimanje referentnog videa sa linka (Instagram, Pinterest, TikTok, YouTube Shorts...) pomocu yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path

BROWSERS = ("chrome", "edge", "firefox", "brave", "opera")


def valid_url(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", url.strip(), re.I))


def _try(url: str, outdir: Path, cookies_browser: str | None) -> Path:
    import yt_dlp

    opts = {
        "outtmpl": str(outdir / "reference_link.%(ext)s"),
        "format": "bv*[height<=1920]+ba/b[height<=1920]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": 300 * 1024 * 1024,
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("entries"):
            info = info["entries"][0]
        path = Path(ydl.prepare_filename(info))
    if path.suffix != ".mp4" and path.with_suffix(".mp4").exists():
        path = path.with_suffix(".mp4")
    if not path.exists():
        found = sorted(outdir.glob("reference_link.*"))
        if not found:
            raise RuntimeError("video nije sacuvan")
        path = found[0]
    return path


def download_reference(url: str, outdir: Path, log=lambda s: None) -> Path:
    """Prvo pokusa bez prijave; ako sajt trazi login (cesto Instagram), proba sa kolacicima iz tvog browsera."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError as e:
        raise RuntimeError("Nedostaje yt-dlp: pokreni ponovo start.bat (ili pip install yt-dlp)") from e
    errors = []
    for browser in (None, *BROWSERS):
        try:
            if browser:
                log(f"Probam preuzimanje uz tvoju prijavu iz browsera ({browser})")
            return _try(url, outdir, browser)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:200]
            errors.append(f"{browser or 'bez prijave'}: {msg}")
            if browser is None and not re.search(r"login|log in|cookie|rate.?limit|private|empty media|401|403",
                                                 msg, re.I):
                break  # greska nije zbog prijave -> nema svrhe probati sa kolacicima
    raise RuntimeError(
        "Ne mogu da preuzmem video sa ovog linka. Proveri da je link do jednog javnog videa "
        "(npr. https://www.instagram.com/reel/...). Ako i dalje ne radi, preuzmi video na racunar i ubaci ga kao fajl. "
        f"Detalji: {errors[-1] if errors else ''}"
    )

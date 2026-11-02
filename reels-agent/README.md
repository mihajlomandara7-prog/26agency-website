# Reels Agent — AI agent za montažu reelsova

Pošalješ **referentni reel** (video kakav želiš) + **svoj materijal** (klipove), a agent napravi isti takav reel od tvog materijala: isti tempo rezova, ritam po muzici, sličan tekst na ekranu, efekte i kolor.

## Kako radi

1. **Analiza reference** (`agent/analyze.py`, ffmpeg): pronalazi tačna vremena rezova, BPM i udarce u muzici i vadi po jedan frejm iz svakog kadra.
2. **Analiza tvojih klipova**: trajanje, orijentacija i 3 frejma po klipu.
3. **Plan montaže** (`agent/planner.py`, Claude): Claude gleda frejmove reference i tvoje frejmove i pravi plan. Za svaki segment bira klip, deo klipa, trajanje (uskladjeno sa rezovima i udarcima), brzinu, efekat (zoom in/out, shake), tranziciju (cut/flash/fade) i tekst. Bira i kolor za ceo video.
4. **Render** (`agent/render.py`, ffmpeg): vertikalni 1080x1920 MP4 sa 30 fps, tekstom i muzikom.
5. **Ispravke**: kad pogledaš video, napišeš npr. „brži rezovi na početku, promeni tekst u 2. kadru“ i agent izmeni plan i ponovo renderuje. Plan možeš da menjaš i ručno, kao JSON.

## Instalacija

Treba ti Python 3.10+ i **ffmpeg**:
- Mac: `brew install ffmpeg`
- Windows: `winget install ffmpeg`
- Linux: `sudo apt install ffmpeg`

```bash
cd reels-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...                  # Windows: set ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

Otvori **http://127.0.0.1:8000**, ubaci referentni reel i svoje klipove, izaberi zvuk i klikni **Napravi reel**.

## Opcije zvuka
- **Muzika iz referentnog reela**: rezovi već prate njen ritam. Pazi na autorska prava ako objavljuješ.
- **Moja muzika**: uploaduješ svoj audio fajl.
- **Originalni zvuk iz klipova**: korisno za talking-head i vlog snimke.

## Podešavanja (env varijable)
| Varijabla | Default | Opis |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | API ključ (obavezno) |
| `REELS_AGENT_MODEL` | `claude-opus-5-5` | Claude model |
| `REELS_AGENT_FONT` | DejaVu/Arial Bold | Putanja do .ttf fonta za tekst |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Adresa servera |

Jobovi i renderi se čuvaju u `reels-agent/data/jobs/<id>/` i ta fascikla se ne commituje.

## Ograničenja (trenutno)
- Do 20 klipova po reelu. Iz reference se analizira najviše 24 kadra.
- Tekst se pozicionira gore, u sredini ili dole, u 4 stila. Animacije teksta (pop-in, karaoke titlovi) još nisu urađene.
- Nema automatskih titlova iz govora.

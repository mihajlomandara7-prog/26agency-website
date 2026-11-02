# Reels Agent — AI agent za montažu reelsova

Pošalješ **referentni reel** (video kakav želiš) + **svoj materijal** (klipove), a agent napravi isti takav reel od tvog materijala: isti tempo rezova, ritam po muzici, sličan tekst na ekranu, efekte i kolor.

## Kako radi

1. **Analiza reference** (`agent/analyze.py`, ffmpeg): pronalazi tačna vremena rezova, BPM i udarce u muzici i vadi po jedan frejm iz svakog kadra.
2. **Analiza tvojih klipova**: trajanje, orijentacija i 3 frejma po klipu.
3. **Prepoznavanje govora** (`agent/transcribe.py`, Whisper lokalno): svaka reč dobija vreme, za titlove i da Claude ne seče usred rečenice.
4. **Plan montaže** (`agent/planner.py`, Claude): Claude gleda frejmove reference (odmah posle reza i sredinu kadra), tvoje frejmove i transkript, pa za svaki segment bira:
   - klip, deo klipa, trajanje (usklađeno sa rezovima i udarcima) i brzinu
   - efekat: zoom in/out, shake
   - tranziciju: cut, flash, fade, **glitch**, **zoom punch**, **swipe levo/gore**, **whip pan**, crossfade, zoom, circle, pixelize, dip to white
   - tekst na ekranu i njegovu **animaciju**: pop, fade, slide up, typewriter
   - za ceo video: kolor i **stil titlova** (karaoke, reč po reč, klasični)
5. **Render** (`agent/render.py` + `agent/subs.py`, ffmpeg + libass): vertikalni 1080x1920 MP4 sa 30 fps. Tranzicije se preklapaju tako da rezovi i dalje padaju na udarce muzike.
6. **Ispravke**: kad pogledaš video, napišeš npr. „brži rezovi na početku, promeni tekst u 2. kadru“ i agent izmeni plan i ponovo renderuje. Plan možeš da menjaš i ručno, kao JSON.

## Instalacija

Treba ti Python 3.10+ i **ffmpeg 6+** (sa libass, što imaju standardne verzije):
- Mac: `brew install ffmpeg`
- Windows: `winget install ffmpeg`
- Linux: `sudo apt install ffmpeg`

```bash
cd reels-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # Windows: copy .env.example .env
# otvori .env i upiši svoj ključ: ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

**API ključ** napraviš na https://console.anthropic.com/settings/keys (klikni „Create Key“). Na Billing stranici treba da dodaš kredit. Fajl `.env` se ne commituje, pa ključ ostaje samo na tvom računaru.

Pri prvom pravljenju titlova Whisper preuzme model „small“ (~470 MB) sa HuggingFace-a, samo jednom.

Otvori **http://127.0.0.1:8000**, ubaci referentni reel i svoje klipove, izaberi zvuk i klikni **Napravi reel**.

## Opcije zvuka
- **Muzika iz referentnog reela**: rezovi već prate njen ritam. Pazi na autorska prava ako objavljuješ.
- **Moja muzika**: uploaduješ svoj audio fajl.
- **Originalni zvuk iz klipova**: korisno za vlog snimke.
- **Govor iz klipova + muzika ispod**: za talking-head. Muzika (tvoja ili iz reference) se automatski stiša dok pričaš (ducking).

## Titlovi
- **Auto**: Claude bira stil najbliži referenci, ako u klipovima ima govora.
- **Karaoke**: fraza od 2-3 reči, a reč koja se izgovara je žuta i malo veća.
- **Reč po reč**: jedna velika reč koja iskače, kao kod Hormozija.
- **Klasični**: obični titlovi po frazama.
- Jezik može da bude auto ili izabran (srpski, hrvatski, bosanski, engleski, nemački).

## Podešavanja (env varijable)
| Varijabla | Default | Opis |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | API ključ (obavezno) |
| `REELS_AGENT_MODEL` | `claude-opus-5-5` | Claude model |
| `REELS_AGENT_FONT` | DejaVu/Arial Bold | Putanja do .ttf fonta za tekst |
| `REELS_AGENT_WHISPER_MODEL` | `small` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3` (veći = tačniji, sporiji) |
| `REELS_AGENT_WHISPER_DEVICE` | `auto` | `cpu` ili `cuda` (NVIDIA GPU) |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Adresa servera |

Jobovi i renderi se čuvaju u `reels-agent/data/jobs/<id>/` i ta fascikla se ne commituje.

## Ograničenja
- Do 20 klipova po reelu. Iz reference se analizira najviše 16 kadrova (po 2 frejma).
- Claude vidi frejmove, ne ceo video u pokretu. Zato animacije teksta i tranzicije iz reference prepoznaje približno, a ne piksel-perfektno.
- Titlovi se prave samo od govora iz klipova. Za voiceover koji nije u klipovima trenutno nema podrške.

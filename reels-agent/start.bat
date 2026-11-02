@echo off
chcp 65001 >nul
title Reels Agent
cd /d "%~dp0"

echo.
echo  === Reels Agent ===
echo.
echo  Proveravam da li ima nove verzije...
git pull --quiet

if not exist ".venv\Scripts\python.exe" (
  echo  Prva instalacija - traje par minuta, sacekaj...
  python -m venv .venv
)
echo  Proveravam pakete...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  Otvaram .env - upisi svoj API kljuc posle ANTHROPIC_API_KEY= pa sacuvaj Ctrl+S i zatvori.
  notepad ".env"
)

echo.
echo  Agent radi! Browser ce se sam otvoriti na http://127.0.0.1:8000
echo  NE ZATVARAJ ovaj prozor dok pravis reelsove. Za gasenje samo zatvori prozor.
echo.
".venv\Scripts\python.exe" app.py --open
pause

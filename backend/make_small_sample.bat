@echo off
rem Writes mltraining\small_sample.json (12,000 reviews, about 18 MB) - small enough to send to Claude for tuning.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
python -m ml.make_sample --reviews ..\mltraining\sample_reviews.json --out ..\mltraining\small_sample.json --n 12000 --total 120005
echo.
echo Done. You can close this window.
pause

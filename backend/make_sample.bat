@echo off
rem Writes mltraining\sample_reviews.json (a 120,000-review random sample) so the model can be tuned off this laptop.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
echo Sampling reviews (about 2-3 minutes)...
python -m ml.make_sample --reviews ..\mltraining\IMDB_reviews.json --out ..\mltraining\sample_reviews.json --n 120000 > logs\sample.txt 2>&1
type logs\sample.txt
echo.
echo Done. You can close this window.
pause

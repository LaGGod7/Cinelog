@echo off
rem Sets the cut-offs of the semantic plot-match layer from real clean reviews (about 7 minutes). Only needed again if you change the encoder.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
python -m ml.calibrate_semantic --reviews ..\mltraining\small_sample.json --movies ..\mltraining\IMDB_movie_details.json --models models > logs\calibrate_semantic.txt 2>&1
type logs\calibrate_semantic.txt
echo.
echo Done. Restart the site to use the new cut-offs.
pause

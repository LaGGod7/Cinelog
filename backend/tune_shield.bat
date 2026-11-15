@echo off
rem Sets the shield's blur / moderator thresholds from data (validation movies the model never trained on).
rem Re-run after every training run, or with different targets: tune_shield.bat 0.10 0.20 0.9  (blur FPR, moderator FPR, spoiler reviews to flag)
rem Third number: the share of spoiler reviews that should be flagged one way or another (blurred, sent to moderators, or given a
rem 'Possible spoilers' label). Higher catches more but labels more clean reviews too; the price is printed. Default 0.8.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
set BLUR=%1
if "%BLUR%"=="" set BLUR=0.08
set ASK=%2
if "%ASK%"=="" set ASK=0.15
set RECALL=%3
if "%RECALL%"=="" set RECALL=0.8
python -m ml.tune_shield --reviews ..\mltraining\small_sample.json --movies ..\mltraining\IMDB_movie_details.json --models models --blur-fpr %BLUR% --ask-fpr %ASK% --recall %RECALL% > logs\tune_shield.txt 2>&1
type logs\tune_shield.txt
echo.
echo Done. Restart the API (close its window, then run start_site.bat) to use the new thresholds.
pause

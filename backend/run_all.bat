@echo off
rem CineLog: evaluate the spoiler model, import plots, then start the API and the website.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist .venv\Scripts\activate.bat (
  echo No .venv found in %cd% - create it first: python -m venv .venv
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
if not exist logs mkdir logs

echo [1/5] Installing missing packages...
pip install -r requirements.txt pandas > logs\pip.txt 2>&1

echo [2/5] Evaluating the spoiler shield (a few minutes)...
python -m ml.eval_shield --reviews ..\mltraining\IMDB_reviews.json --movies ..\mltraining\IMDB_movie_details.json --models models > logs\eval.txt 2>&1
type logs\eval.txt

echo [3/5] Importing 300 films with plots from TMDB...
python -m scripts.import_kaggle --movies ..\mltraining\IMDB_movie_details.json --limit 300 > logs\import.txt 2>&1
type logs\import.txt

echo [4/5] Starting the API on http://localhost:8000 ...
start "CineLog API" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:create_app --factory --port 8000"

echo [5/5] Starting the website on http://localhost:5173 ...
cd ..\frontend
if not exist node_modules call npm install > ..\backend\logs\npm.txt 2>&1
start "CineLog Web" cmd /k "npm run dev"
timeout /t 10 /nobreak > nul
start http://localhost:5173
echo.
echo Done. Logs are in backend\logs. Close the two CineLog windows to stop the site.
pause

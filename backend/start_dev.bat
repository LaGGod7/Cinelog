@echo off
rem Development mode: API on 8000 and the hot-reloading front end on 5173 (slower to load than start_site.bat).
cd /d "%~dp0"
start "CineLog API" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:create_app --factory --port 8000 --log-level warning"
cd ..\frontend
if not exist node_modules call npm install
start "CineLog Web" cmd /k "npm run dev"
timeout /t 8 /nobreak > nul
start http://localhost:5173

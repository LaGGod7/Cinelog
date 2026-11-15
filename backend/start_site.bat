@echo off
rem Starts CineLog (website + API) on ONE port from the pre-built website: fast. Close this window to stop it.
rem Developing the front end? Use start_dev.bat instead.
cd /d "%~dp0"
set SERVE_FRONTEND=1
if "%FRONTEND_URL%"=="" set FRONTEND_URL=http://localhost:8000
if not exist "..\frontend\dist\index.html" (
  echo Building the website once - this takes a minute...
  pushd ..\frontend
  if not exist node_modules call npm install
  call npm run build
  popd
)
call .venv\Scripts\activate.bat
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"
echo CineLog is running at http://localhost:8000   (close this window to stop it)
uvicorn app.main:create_app --factory --port 8000 --log-level warning

@echo off
rem Checks that this laptop can reach TMDB with the key in backend\.env, and that search works. Output is saved to logs\check_tmdb.txt
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
python -m scripts.check_tmdb > logs\check_tmdb.txt 2>&1
type logs\check_tmdb.txt
echo.
pause

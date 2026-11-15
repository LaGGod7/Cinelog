@echo off
rem Fills the site with made-up reviews (users garbage01@cinelog.dev ...) and runs every one through the Spoiler Shield, then scores it.
rem Needs the demo films (it runs seed_demo for you if they are missing). Stop the site first (SQLite does not like two writers).
rem   spoiler_test.bat           add the made-up reviews and score them (the report is also saved in logs\spoiler_test.txt)
rem   spoiler_test.bat --clean   remove the made-up users and reviews again
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
python -m scripts.seed_spoiler_test %1 > logs\spoiler_test.txt 2>&1
type logs\spoiler_test.txt
echo.
pause

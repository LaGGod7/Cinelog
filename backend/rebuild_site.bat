@echo off
rem Rebuilds the website files in frontend\dist (only needed after the front-end source changes).
cd /d "%~dp0..\frontend"
if not exist node_modules call npm install
call npm run build
echo Done. Restart start_site.bat.
pause

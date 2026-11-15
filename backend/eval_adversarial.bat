@echo off
rem Stress test: reviews that give the story away without looking like it (set A and a fresh set B), plus clean reviews that sound spoilery.
rem Runs offline against the models in models\ and saves the report to logs\adversarial.txt.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
echo ===== set A ===== > logs\adversarial.txt
python -m ml.eval_adversarial --models models >> logs\adversarial.txt 2>&1
echo. >> logs\adversarial.txt
echo ===== set B (written after set A was measured) ===== >> logs\adversarial.txt
python -m ml.eval_adversarial --models models --gold ml\gold_adversarial_b.json >> logs\adversarial.txt 2>&1
type logs\adversarial.txt
echo.
pause

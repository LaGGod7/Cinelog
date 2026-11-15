@echo off
rem Sentence-level check of the Spoiler Shield against the hand-labelled gold set (ml\gold_sentences.json).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
python -m ml.eval_sentences --movies ..\mltraining\IMDB_movie_details.json --models models > logs\eval_sentences.txt 2>&1
type logs\eval_sentences.txt
echo.
pause

@echo off
rem Trains the recurrent spoiler layer (BiGRU + attention) on your Kaggle data, blends it with the trained model, and tunes the blend.
rem Uses your GPU if PyTorch can see one, otherwise the CPU. Output is also written to logs\train_rnn.txt and logs\tune_shield.txt.
rem Usage: train_rnn.bat [reviews]   e.g.  train_rnn.bat 150000   (default 100000; a smaller number is faster)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
set N=%1
if "%N%"=="" set N=100000

if not exist models\spoiler_ml.joblib (
  echo Train the main spoiler model first: run train.bat
  pause
  exit /b 1
)
python -c "import torch" >nul 2>&1
if errorlevel 1 (
  echo [1/3] Installing PyTorch ^(needed only for training, the site itself does not use it^)...
  if not exist .piptmp mkdir .piptmp
  set TEMP=%cd%\.piptmp
  set TMP=%cd%\.piptmp
  pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu128 > logs\pip_rnn.txt 2>&1
  python -c "import torch" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo PyTorch did not install. The last lines of the log:
    powershell -NoProfile -Command "Get-Content logs\pip_rnn.txt -Tail 6"
    pause
    exit /b 1
  )
) else (
  echo [1/3] PyTorch is already installed.
)

echo [2/3] Training on %N% reviews ^(downloads 134 MB of GloVe word vectors the first time^). This takes a while...
python -u -m ml.train_rnn --reviews ..\mltraining\IMDB_reviews.json --movies ..\mltraining\IMDB_movie_details.json --out models --max-reviews %N% --epochs 4 --hidden 96 --max-len 200 > logs\train_rnn.txt 2>&1
if errorlevel 1 (
  echo Training failed. The last lines of logs\train_rnn.txt:
  powershell -NoProfile -Command "Get-Content logs\train_rnn.txt -Tail 12"
  pause
  exit /b 1
)
powershell -NoProfile -Command "Get-Content logs\train_rnn.txt -Tail 14"

echo.
echo [3/3] Measuring the blend with the model the site really runs, and setting its thresholds...
python -m ml.tune_shield --reviews ..\mltraining\small_sample.json --movies ..\mltraining\IMDB_movie_details.json --models models --recall 0.8 > logs\tune_shield.txt 2>&1
type logs\tune_shield.txt
echo.
echo Done. If the blend line says the gain interval includes 0, the recurrent layer is not clearly better yet; more reviews help.
echo Restart the site (close its window, run start_site.bat) to use it.
pause

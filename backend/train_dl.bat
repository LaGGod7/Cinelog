@echo off
rem Trains the deep spoiler model on your GPU and saves it to backend\models. Output is also written to logs\train_dl.txt (UTF-8, readable by any tool).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate.bat
if not exist logs mkdir logs

echo [1/3] Installing PyTorch with GPU support (a 2.8 GB download; needs about 10 GB free on this drive)...
rem Download and unpack on this drive instead of C:, which ran out of space last time.
if not exist .piptmp mkdir .piptmp
set TEMP=%cd%\.piptmp
set TMP=%cd%\.piptmp
pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu128 > logs\pip_dl.txt 2>&1
if errorlevel 1 (
  echo.
  echo PyTorch did not install. The last lines of the log:
  powershell -NoProfile -Command "Get-Content logs\pip_dl.txt -Tail 6"
  echo.
  echo If it says "No space left on device", free up disk space and run this again.
  pause
  exit /b 1
)
pip install --no-cache-dir transformers tokenizers onnx onnxscript onnxruntime >> logs\pip_dl.txt 2>&1
rmdir /s /q .piptmp 2>nul

echo [2/3] Checking the GPU...
python -c "import torch; ok=torch.cuda.is_available(); print('GPU found:', torch.cuda.get_device_name(0) if ok else 'NONE - training would run on the CPU and take many hours'); raise SystemExit(0 if ok else 1)"
if errorlevel 1 (
  echo.
  echo No GPU was detected by PyTorch. Stop here and send Claude the file logs\pip_dl.txt
  pause
  exit /b 1
)

echo [3/3] Training (roughly 30-60 minutes on an RTX 4050; progress prints every 200 steps)...
powershell -NoProfile -Command "Remove-Item logs\train_dl.txt -ErrorAction SilentlyContinue; python -u -m ml.train_dl --reviews ..\mltraining\IMDB_reviews.json --movies ..\mltraining\IMDB_movie_details.json --out models --max-reviews 120000 --epochs 2 2>&1 | ForEach-Object { $s = $_.ToString(); Write-Host $s; Add-Content -Path logs\train_dl.txt -Value $s -Encoding utf8 }"
echo.
echo Finished. The deep model is saved but stays switched off (USE_DL=false) until it has been evaluated against the ML model.
pause

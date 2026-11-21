@echo off
chcp 65001 >nul
rem Отдельное окружение для сравнения моделей распознавания (#3. ASR Bench.py).
rem Основной Python и WhisperX не трогает. Модели качаются с Hugging Face (~3,5 ГБ),
rem плюс CUDA/cuDNN для видеокарты (~2 ГБ, только внутри %USERPROFILE%\.cache\venv-asr).
cd /d "%~dp0"
set V=%USERPROFILE%\.cache\venv-asr
if not exist "%V%\Scripts\python.exe" python -m venv "%V%"
"%V%\Scripts\python.exe" -m pip install -U pip
"%V%\Scripts\python.exe" -m pip install "onnx-asr[hub]" "onnxruntime-gpu[cuda,cudnn]"
"%V%\Scripts\python.exe" -c "import onnxruntime as o; o.preload_dlls(); print('Видеокарта:', 'CUDAExecutionProvider' in o.get_available_providers()); import onnx_asr; [print('OK', m, onnx_asr.load_model(m) and '') for m in ('gigaam-v3-e2e-rnnt', 'nemo-parakeet-tdt-0.6b-v3', 'nemo-canary-1b-v2')]"
echo.
echo Готово. Напиши Claude, что всё установлено.
pause

# Одноразова підготовка середовища для завдання 1.1 (порівняння розпізнавачів).
# Створює окреме віртуальне середовище в корені репозиторію і ставить туди
# три стеки: faster-whisper (CTranslate2), onnx-asr (onnxruntime-gpu) і jiwer.
#
# Чому окреме середовище, а не системний Python: нам потрібні три різні
# нативні бібліотеки з CUDA, і кожна з них по-своєму шукає DLL. У спільному
# середовищі конфлікт версій onnxruntime та onnxruntime-gpu мовчазний:
# пакет вантажиться, але працює на процесорі.
#
# Запуск з PowerShell:
#   & "D:\Local Cluster\scripts\asr-setup.ps1"
#   & "D:\Local Cluster\scripts\asr-setup.ps1" -BasePython "C:\Python313\python.exe"

param([string]$BasePython = "python")

$ErrorActionPreference = "Stop"
$Root = "D:\Local Cluster"
$Venv = Join-Path $Root ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"

Write-Host "== base python ==" -ForegroundColor Cyan
& $BasePython --version
& $BasePython -c "import sys; print(sys.executable)"

if (-not (Test-Path $Py)) {
    Write-Host "== creating venv: $Venv ==" -ForegroundColor Cyan
    & $BasePython -m venv $Venv
} else {
    Write-Host "== venv already exists: $Venv ==" -ForegroundColor Yellow
}

Write-Host "== upgrading pip ==" -ForegroundColor Cyan
& $Py -m pip install --upgrade pip --quiet

Write-Host "== installing packages ==" -ForegroundColor Cyan
# faster-whisper  - Whisper на CTranslate2, обидва наші кандидати з цього сімейства
# onnx-asr[gpu]   - Parakeet TDT 0.6b v3 через onnxruntime-gpu, без важкого NeMo
# onnx-asr[hub]   - завантаження ваг з HuggingFace
# jiwer           - рахує WER і CER, коли дійдемо до еталона
# nvidia-*        - cuBLAS і cuDNN 9 для CUDA 12; саме їх шукає CTranslate2 на Windows
& $Py -m pip install `
    "faster-whisper" `
    "onnx-asr[gpu,hub]" `
    "jiwer" `
    "nvidia-cublas-cu12" `
    "nvidia-cudnn-cu12"

Write-Host "== result ==" -ForegroundColor Cyan
& $Py "$Root\scripts\asr-env.py"

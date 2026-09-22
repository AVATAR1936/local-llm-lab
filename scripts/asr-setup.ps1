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
#
# Без аргументів скрипт сам знайде інтерпретатор і пропустить збірку зі Store.

param([string]$BasePython = "")

$ErrorActionPreference = "Stop"
$Root = "D:\Local Cluster"
$Venv = Join-Path $Root ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"

# Знайти справжній python.exe. Складність у тому, що "py -3.13" це програма
# з аргументом, а не шлях, і викликати його через & одним рядком не можна.
# Тому спершу питаємо лаунчер, де лежить інтерпретатор, і далі працюємо
# вже з конкретним exe. Заодно відсіюємо збірку з Microsoft Store: вона
# лежить у WindowsApps і є перенаправленим ярликом, а не повноцінною
# установкою, з якою добре живуть нативні бібліотеки CUDA.
function Resolve-BasePython {
    param([string]$Hint)

    if ($Hint -and (Test-Path $Hint)) { return (Resolve-Path $Hint).Path }

    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.13", "-3.12", "-3.11")) {
            try {
                $exe = & py $v -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += $exe.Trim() }
            } catch { }
        }
    }
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        "C:\Python313\python.exe"
    )
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += (Get-Command python).Source
    }

    foreach ($c in $candidates) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        if ($c -like "*WindowsApps*") {
            Write-Host "  skip (Microsoft Store): $c" -ForegroundColor DarkYellow
            continue
        }
        return (Resolve-Path $c).Path
    }
    throw "No suitable python.exe found. Pass one explicitly: -BasePython 'C:\path\to\python.exe'"
}

Write-Host "== base python ==" -ForegroundColor Cyan
$Base = Resolve-BasePython -Hint $BasePython
Write-Host "  $Base"
& $Base --version

if (-not (Test-Path $Py)) {
    Write-Host "== creating venv: $Venv ==" -ForegroundColor Cyan
    & $Base -m venv $Venv
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

# Установка всего для Saturni · Editor на новом компьютере (Windows 11, видеокарта NVIDIA).
# Запуск из PowerShell (лучше от администратора — для winget):
#   powershell -ExecutionPolicy Bypass -File "D:\@Hub\# Saturni · Editor\@github\install.ps1"
# Скрипт можно запускать повторно: что уже стоит — пропускается. В конце — список того, что не встало.

$ErrorActionPreference = 'Continue'
$Hub = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$E   = Join-Path $Hub '# Saturni · Editor'
$Fails = New-Object System.Collections.Generic.List[string]
function Step($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Check($what) { if ($LASTEXITCODE -ne 0) { $Fails.Add("$what (код $LASTEXITCODE)") } }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }
function WG($id) { winget install -e --id $id --silent --accept-source-agreements --accept-package-agreements; Refresh-Path }

# Настоящий Python 3.12. Команда «python» без установленного Python открывает Microsoft Store — её не считаем.
function Find-Python {
    $cands = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe')
    )
    if (Has py) { try { $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { $cands = @($p.Trim()) + $cands } } catch {} }
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

if ($Hub -ne 'D:\@Hub') {
    Write-Host "ВНИМАНИЕ: репозиторий лежит в $Hub, а не в D:\@Hub. Часть скриптов ждёт D:\@Hub (список — в @links.md каждой программы)." -ForegroundColor Yellow
}

Step '1. Программы: Python 3.12, Node.js, ffmpeg, Git'
$Py = Find-Python
if (-not $Py) { WG 'Python.Python.3.12'; $Py = Find-Python }
if (-not $Py) {
    Write-Host 'Python 3.12 не нашёлся и не поставился. Поставь вручную с python.org (галочка «Add to PATH») и запусти скрипт снова.' -ForegroundColor Red
    exit 1
}
Write-Host "Python: $Py"
if (-not (Has node))   { WG 'OpenJS.NodeJS' }
if (-not (Has ffmpeg)) { WG 'Gyan.FFmpeg' }
if (-not (Has git))    { WG 'Git.Git' }

Step '2. Основной Python: torch с CUDA и библиотеки'
& $Py -m pip install -U pip
& $Py -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128; Check 'torch (основной Python)'
& $Py -m pip install -r (Join-Path $PSScriptRoot 'requirements-main.txt'); Check 'библиотеки основного Python'

Step '3. Audio Cleaner: своё окружение в %USERPROFILE%\.stemstudio'
$SS = Join-Path $env:USERPROFILE '.stemstudio'
$V  = Join-Path $SS 'venv\Scripts\python.exe'
if (-not (Test-Path $V)) { & $Py -m venv (Join-Path $SS 'venv') }
if (Test-Path $V) {
    & $V -m pip install -U pip
    & $V -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124; Check 'torch (Audio Cleaner)'
    & $V -m pip install -r (Join-Path $PSScriptRoot 'requirements-audio-cleaner.txt'); Check 'библиотеки Audio Cleaner'
} else { $Fails.Add('окружение Audio Cleaner не создалось') }
if (-not (Test-Path (Join-Path $SS 'msst'))) { git clone https://github.com/ZFTurbo/Music-Source-Separation-Training (Join-Path $SS 'msst') }
# Строка #! в начале «# Saturni · Audio Cleaner.pyw» должна указывать на этот venv
$AC = Join-Path $E '#Audio Cleaner\# Saturni · Audio Cleaner.pyw'
$first = (Get-Content -LiteralPath $AC -TotalCount 1)
$want = '#!' + (Join-Path $SS 'venv\Scripts\pythonw.exe')
if ($first -like '#!*' -and $first -ne $want) {
    $all = Get-Content -LiteralPath $AC -Encoding UTF8; $all[0] = $want
    Set-Content -LiteralPath $AC -Value $all -Encoding UTF8
}
if (-not (Test-Path (Join-Path $SS 'models\bandit_plus_dnr.chpt'))) {
    Write-Host 'Модель разделения голоса (bandit_plus_dnr.chpt + config_dnr_bandit.yaml) положи в' (Join-Path $SS 'models') -ForegroundColor Yellow
}

Step '4. Распознавание GigaAM / Parakeet: окружение %USERPROFILE%\.cache\venv-asr (~5 ГБ)'
$ans = Read-Host 'Ставить сейчас? (y/n)'
if ($ans -eq 'y') {
    $VA = Join-Path $env:USERPROFILE '.cache\venv-asr'
    $VAP = Join-Path $VA 'Scripts\python.exe'
    if (-not (Test-Path $VAP)) { & $Py -m venv $VA }
    & $VAP -m pip install -U pip
    & $VAP -m pip install "onnx-asr[hub]" "onnxruntime-gpu[cuda,cudnn]"; Check 'GigaAM (venv-asr)'
    & $VAP -c "import onnxruntime as o; o.preload_dlls(); print('Видеокарта:', 'CUDAExecutionProvider' in o.get_available_providers()); import onnx_asr; [onnx_asr.load_model(m) for m in ('gigaam-v3-e2e-rnnt', 'nemo-parakeet-tdt-0.6b-v3', 'nemo-canary-1b-v2')]; print('Модели скачаны')"
    Check 'модели GigaAM / Parakeet'
}

Step '5. Node: Auto Editor (Remotion) и Premiere MCP'
Push-Location -LiteralPath (Join-Path $E '#Auto Editor'); npm ci; Check 'Auto Editor (npm)'; Pop-Location
Push-Location -LiteralPath (Join-Path $E '#Series\@tools\mcp\premiere-pro-mcp'); npm ci; Check 'Premiere MCP (npm)'; npm run build; Check 'Premiere MCP (сборка)'; Pop-Location

Step '6. Premiere: .mcp.json и панель Motion Tracker'
$Mcp = Join-Path $E '.mcp.json'
if (-not (Test-Path $Mcp)) {
    $tok = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'mcp.json.example') -Raw -Encoding UTF8) -replace 'ПРИДУМАЙ-[^"]+', $tok |
        Set-Content -LiteralPath $Mcp -Encoding UTF8
    Write-Host "Создан .mcp.json. Пароль моста для панели плагина в Premiere: $tok" -ForegroundColor Yellow
}
# Панель Motion Tracker — CEP-расширение: ссылка из папки Adobe на #Motion Tracker\ui
$Cep = Join-Path $env:APPDATA 'Adobe\CEP\extensions'
New-Item -ItemType Directory -Force $Cep | Out-Null
$Link = Join-Path $Cep 'Saturni · Motion Tracker'
if (-not (Test-Path $Link)) { New-Item -ItemType Junction -Path $Link -Target (Join-Path $E '#Motion Tracker\ui') | Out-Null }
# Неподписанные CEP-панели работают только с PlayerDebugMode=1
foreach ($v in 11..13) { New-Item -Path "HKCU:\Software\Adobe\CSXS.$v" -Force | Out-Null; Set-ItemProperty -Path "HKCU:\Software\Adobe\CSXS.$v" -Name PlayerDebugMode -Value '1' }

Step 'Проверка'
& $Py -c "import torch, webview, cv2, whisperx; print('CUDA:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
Check 'проверка основного Python (torch, webview, cv2, whisperx)'
try {
    $enc = & ffmpeg -hide_banner -encoders 2>$null
    if ($enc -match 'h264_nvenc') { Write-Host 'ffmpeg: работает, NVENC есть' } else { $Fails.Add('ffmpeg без NVENC') }
} catch {
    $Fails.Add('ffmpeg не запускается: ' + $_.Exception.Message)
}

if ($Fails.Count) {
    Write-Host "`nНЕ ВСТАЛО:" -ForegroundColor Red
    $Fails | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    Write-Host 'Пришли этот список Claude. Скрипт можно запустить снова — готовое пропустится.' -ForegroundColor Yellow
} else {
    Write-Host "`nГотово, всё встало. Остальное вручную — см. README.md (раздел «Вручную»)." -ForegroundColor Green
}

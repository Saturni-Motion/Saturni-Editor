# Установка всего для Saturni · Editor на новом компьютере (Windows 11, видеокарта NVIDIA).
# Запуск из PowerShell (лучше от администратора — для winget):
#   powershell -ExecutionPolicy Bypass -File "D:\@Hub\# Saturni · Editor\@github\install.ps1"
# Скрипт можно запускать повторно: что уже стоит — пропускается.

$ErrorActionPreference = 'Continue'
$Hub = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$E   = Join-Path $Hub '# Saturni · Editor'
function Step($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

if ($Hub -ne 'D:\@Hub') {
    Write-Host "ВНИМАНИЕ: репозиторий лежит в $Hub, а не в D:\@Hub. Часть скриптов ждёт D:\@Hub (список — в @links.md каждой программы)." -ForegroundColor Yellow
}

Step '1. Программы: Python 3.12, Node.js, ffmpeg, Git'
if (-not (Has py) -and -not (Has python)) { winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements }
if (-not (Has node))   { winget install -e --id OpenJS.NodeJS --silent --accept-source-agreements --accept-package-agreements }
if (-not (Has ffmpeg)) { winget install -e --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements }
if (-not (Has git))    { winget install -e --id Git.Git --silent --accept-source-agreements --accept-package-agreements }
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$Py = if (Has py) { 'py' } else { 'python' }
$PyArgs = if ($Py -eq 'py') { @('-3.12') } else { @() }

Step '2. Основной Python: torch с CUDA и библиотеки'
& $Py @PyArgs -m pip install -U pip
& $Py @PyArgs -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
& $Py @PyArgs -m pip install -r (Join-Path $PSScriptRoot 'requirements-main.txt')

Step '3. Audio Cleaner: своё окружение в %USERPROFILE%\.stemstudio'
$SS = Join-Path $env:USERPROFILE '.stemstudio'
$V  = Join-Path $SS 'venv\Scripts\python.exe'
if (-not (Test-Path $V)) { & $Py @PyArgs -m venv (Join-Path $SS 'venv') }
& $V -m pip install -U pip
& $V -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
& $V -m pip install -r (Join-Path $PSScriptRoot 'requirements-audio-cleaner.txt')
if (-not (Test-Path (Join-Path $SS 'msst'))) { git clone https://github.com/ZFTurbo/Music-Source-Separation-Training (Join-Path $SS 'msst') }
# Строка #! в начале «# Saturni · Audio Cleaner.pyw» указывает на этот venv по пути пользователя SATURNi.
$AC = Join-Path $E '#Audio Cleaner\# Saturni · Audio Cleaner.pyw'
$first = (Get-Content -LiteralPath $AC -TotalCount 1)
$want = '#!' + (Join-Path $SS 'venv\Scripts\pythonw.exe')
if ($first -like '#!*' -and $first -ne $want) {
    $all = Get-Content -LiteralPath $AC -Encoding UTF8; $all[0] = $want
    Set-Content -LiteralPath $AC -Value $all -Encoding UTF8
}
Write-Host 'Модель разделения голоса (bandit_plus_dnr.chpt + config_dnr_bandit.yaml) положи в' (Join-Path $SS 'models') -ForegroundColor Yellow

Step '4. Распознавание GigaAM / Parakeet: окружение %USERPROFILE%\.cache\venv-asr (~5 ГБ)'
$ans = Read-Host 'Ставить сейчас? (y/n)'
if ($ans -eq 'y') { & cmd /c "`"$E\#Series\@tools\#3. ASR Bench - установка.cmd`"" }

Step '5. Node: Auto Editor (Remotion) и Premiere MCP'
Push-Location -LiteralPath (Join-Path $E '#Auto Editor'); npm ci; Pop-Location
Push-Location -LiteralPath (Join-Path $E '#Series\@tools\mcp\premiere-pro-mcp'); npm ci; npm run build; Pop-Location

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
& $Py @PyArgs -c "import torch, webview, cv2, whisperx; print('CUDA:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
ffmpeg -hide_banner -encoders 2>$null | Select-String 'h264_nvenc' | ForEach-Object { 'NVENC: есть' }
Write-Host "`nГотово. Остальное вручную — см. README.md (раздел «Вручную»)." -ForegroundColor Green

# Saturni · Editor -> GitHub
# Копирует важное (код, настройки, инструкции) в отдельную папку-репозиторий и отправляет на GitHub.
# Медиа, кэши браузера, отладочные записи, node_modules, рабочие сессии и разборы серий не копируются.
# Запуск:  powershell -ExecutionPolicy Bypass -File "D:\@Hub\# Saturni · Editor\@github\sync.ps1" [-Message "что поменялось"] [-NoPush]

param([string]$Message = "", [switch]$NoPush)
$ErrorActionPreference = 'Stop'

$Hub  = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # D:\@Hub
$Repo = 'D:\# GitHub\Saturni-Editor'
New-Item -ItemType Directory -Force $Repo | Out-Null
# robocopy /MIR не удаляет в копии то, что исключено, поэтому копия каждый раз собирается заново (кроме .git)
Get-ChildItem -LiteralPath $Repo -Force | Where-Object Name -ne '.git' | Remove-Item -Recurse -Force

# Папки с этими именами не берём нигде
$XD = @('node_modules', '__pycache__', '.git', '⿻', 'webview', 'sessions', 'cache', '#Analysis', '_work', 'logs',
        'Crashpad', 'landing', 'artifacts', 'product-growth-runs', 'Adobe Premiere Pro Audio Previews',
        'Adobe Premiere Pro Auto-Save', '.venv', 'venv')
# Файлы с такими масками не берём
$XF = @('*.wav', '*.mp3', '*.mp4', '*.mov', '*.mkv', '*.m4a', '*.aac', '*.flac', '*.dmp', '*.log', '*.npy',
        '*.prproj', '*.pack', '*.pyc', '.mcp.json', 'desktop.ini', 'Thumbs.db', '*.tmp')

function Sync-Dir([string]$Src, [string]$Dst, [string[]]$ExtraXD = @(), [string[]]$ExtraXF = @()) {
    $ra = @($Src, $Dst, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1', '/XD') + $XD + $ExtraXD + @('/XF') + $XF + $ExtraXF
    & robocopy @ra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy упал ($LASTEXITCODE): $Src" }
}

$E = Join-Path $Hub '# Saturni · Editor'
# Главная папка: монтаж, нарезки, автомонтаж, субтитры, Motion Tracker, Audio Cleaner
Sync-Dir $E (Join-Path $Repo '# Saturni · Editor') `
    -ExtraXD @((Join-Path $E '#Auto Editor\public'), (Join-Path $E '#Auto Editor\work\cf'), (Join-Path $E '#Auto Editor\work\chk'),
               (Join-Path $E '#Auto Editor\work\tw'), (Join-Path $E '#Series\@tools\!verticals')) `
    -ExtraXF @('_s_*.png', '_sheet_stills.png', '_tw*.png', 'fz.png', 'transcripts.json')
# Общие модули, которые эти программы подключают
Sync-Dir (Join-Path $Hub '@ Saturni · Debug') (Join-Path $Repo '@ Saturni · Debug')
Sync-Dir (Join-Path $Hub '@ Saturni · Voice') (Join-Path $Repo '@ Saturni · Voice')
$SB = Join-Path $Repo '@ Saturni · Status Bar'
New-Item -ItemType Directory -Force $SB | Out-Null
Copy-Item -LiteralPath (Join-Path $Hub '@ Saturni · Status Bar\@StatusBar.py'), (Join-Path $Hub '@ Saturni · Status Bar\@links.md') -Destination $SB -Force
# Общие правила Saturni для Claude
Sync-Dir (Join-Path $Hub '⿻\@ Claude\@ INSTRUCTIONS') (Join-Path $Repo '⿻\@ Claude\@ INSTRUCTIONS')

# Корень репозитория: README, установка, .gitignore
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $Repo 'README.md') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'repo.gitignore') -Destination (Join-Path $Repo '.gitignore') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'repo.gitattributes') -Destination (Join-Path $Repo '.gitattributes') -Force

# Проверка: ни одного файла больше 95 МБ (лимит GitHub 100 МБ) и ни одного похожего на ключ
$big = Get-ChildItem -LiteralPath $Repo -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.Length -gt 95MB }
if ($big) { throw "Слишком большие файлы: $($big.FullName -join ', ')" }
$leak = Get-ChildItem -LiteralPath $Repo -Recurse -File -Force -Include *.py,*.pyw,*.json,*.js,*.cjs,*.mjs,*.ts,*.md,*.toml,*.txt,*.yaml,*.cmd,*.ps1 |
    Where-Object { $_.FullName -notmatch '\\(\.git|node_modules)\\' } |
    Select-String -Pattern 'hf_[A-Za-z0-9]{30,}', 'sk-ant-[A-Za-z0-9_-]{20,}', 'ghp_[A-Za-z0-9]{30,}', 'PREMIERE_UXP_TOKEN"\s*:\s*"[A-Za-z0-9_-]{16,}' -List
if ($leak) { throw "Похоже на ключ/токен: $($leak | ForEach-Object { $_.Path + ':' + $_.LineNumber } | Out-String)" }

Set-Location -LiteralPath $Repo
if (-not (Test-Path '.git')) { git init -b main | Out-Null }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Output 'Изменений нет.'; return }
if (-not $Message) { $Message = 'Обновление ' + (Get-Date -Format 'dd.MM.yyyy HH:mm') }
git commit -q -m $Message
if (-not $NoPush) { git push -q origin main; Write-Output 'Отправлено на GitHub.' }

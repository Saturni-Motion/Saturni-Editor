# Saturni · Editor

Монтаж, нарезки, автомонтаж и субтитры Saturni — программы на Python (pywebview) и Node, Windows 11 + NVIDIA.

| Папка | Что это |
|---|---|
| `# Saturni · Editor/# Editor` | Editor: обрезка, склейка, кроп, звук для видео, аудио и фото |
| `# Saturni · Editor/#Series` | Нарезки сериалов: транскрипция, тишина, хайлайты, субтитры, вертикалки, рендер через Premiere |
| `# Saturni · Editor/#Auto Editor` | Автомонтаж (Remotion + HyperFrames) |
| `# Saturni · Editor/#Subtitles` | Subs Studio (правка субтитров), Subs Move, общий запуск `# Saturni · Subs.pyw` |
| `# Saturni · Editor/#Motion Tracker` | Трекинг движения + панель для Premiere |
| `# Saturni · Editor/#Audio Cleaner` | Чистка голоса от музыки и шума |
| `@ Saturni · Debug`, `@ Saturni · Voice`, `@ Saturni · Status Bar` | Общие модули, которые подключают программы выше |
| `⿻/@ Claude/@ INSTRUCTIONS` | Правила Saturni для Claude (стиль ответов, интерфейс, система) |

## Установка на новом компьютере

**1. Скачать в `D:\@Hub`.** Часть скриптов ждёт именно этот путь.

```powershell
winget install -e --id Git.Git
```

```powershell
git clone https://github.com/<аккаунт>/Saturni-Editor.git "D:\@Hub"
```

Если `D:\@Hub` уже есть и не пустая — скачать в другую папку и перенести содержимое внутрь `D:\@Hub`.

**2. Запустить установку** (Python 3.12, Node, ffmpeg, torch с CUDA, библиотеки, Node-пакеты, панель Premiere):

```powershell
powershell -ExecutionPolicy Bypass -File "D:\@Hub\# Saturni · Editor\@github\install.ps1"
```

**3. Вручную:**

- Драйвер NVIDIA (свежий, для CUDA 12.8).
- Adobe Premiere Pro 2026 + UXP Developer Tool: загрузить плагин `# Saturni · Editor/#Series/@tools/mcp/premiere-pro-mcp/uxp-plugin`, в его панели вписать пароль моста из `.mcp.json`.
- Audio Cleaner: модель `bandit_plus_dnr.chpt` и `config_dnr_bandit.yaml` (релизы Music-Source-Separation-Training) положить в `%USERPROFILE%\.stemstudio\models` — в GitHub не влезает (больше 100 МБ).
- Меню Проводника (Nilesoft Shell) и ярлыки — из `@links.md` каждой программы.
- Для Claude Code: `C:\Users\<имя>\.claude\CLAUDE.md` со ссылкой на `D:\@Hub\⿻\@ Claude\@ INSTRUCTIONS`.

## Что скачается само при первом запуске

Модели WhisperX (`large-v3`, ~3 ГБ), Silero VAD, выравнивание WhisperX для русского — в `%USERPROFILE%\.cache`.

## Сколько места нужно

| Что | Примерно |
|---|---|
| Сам репозиторий | см. размер на GitHub |
| Основной Python с torch CUDA | 6 ГБ |
| Audio Cleaner (`.stemstudio\venv`) | 5 ГБ |
| GigaAM / Parakeet (`.cache\venv-asr` + модели) | 5,5 ГБ |
| Модели WhisperX | 3–4 ГБ |
| node_modules (Auto Editor + MCP) | 0,7 ГБ |

## Чего здесь нет

Видео, звук, кэши браузера, отладочные записи, рабочие сессии субтитров и разборы серий (`#Analysis`) — они остаются только на основном компьютере.

## Обновление (на основном компьютере)

```powershell
powershell -ExecutionPolicy Bypass -File "D:\@Hub\# Saturni · Editor\@github\sync.ps1" -Message "что поменялось"
```

На другом компьютере — `git pull` в `D:\@Hub`.

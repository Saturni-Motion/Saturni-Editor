# -*- coding: utf-8 -*-
"""
Explorer Restart — перезапуск Проводника без потери открытых окон.

restart_explorer(): запоминает окна Проводника и их вкладки (Windows 11), перезапускает Проводник, открывает те же окна
с теми же вкладками в том же порядке, потом перезапускает ! AutoMates.ahk (его горячие клавиши и значки в трее
после перезапуска Проводника отваливаются).

Как: Shell.Application.Windows() отдаёт каждую вкладку отдельно, у вкладок одного окна общий HWND. Новая вкладка в окне —
команда 0xA21B самому окну (как Ctrl+T, но без нажатия клавиш и без фокуса), потом Navigate2 в нужную папку.

  from explorer_restart import restart_explorer   (sys.path: <Hub>\\@ Saturni · Explorer)
  python "Explorer Restart.py" [--no-automates | --save | --restore файл.json]
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))          # ⿻\@ Claude\@ INSTRUCTIONS -> Hub
AUTOMATES = os.path.join(HUB, "# Saturni \u00b7 Enhancers", "! AutoMates.ahk")
AHK = r"C:\Program Files\AutoHotkey\AutoHotkey.exe"
NO_WINDOW = 0x08000000
STATE = os.path.join(HUB, "\u2ffb", "@ Claude", "temp", "explorer-windows.json")   # последнее сохранённое: на случай сбоя


def _ps(script, timeout=60):
    # Add-Type компилирует во временную папку: путь с «⿻» компилятор не открывает — берём системную Temp.
    env = dict(os.environ)
    env["TEMP"] = env["TMP"] = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Windows"), "Temp")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
                       capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=env)
    return r.stdout.decode("utf-8", "replace").strip()


def save_windows():
    """[[путь вкладки 1, путь вкладки 2, …], …] — по окнам, вкладки в порядке Проводника."""
    out = _ps("$s = New-Object -ComObject Shell.Application; @($s.Windows() | ? { $_.FullName -match 'explorer\\.exe$' } | "
              "% { [pscustomobject]@{h=[int64]$_.HWND; p=[string]$_.Document.Folder.Self.Path} }) | ConvertTo-Json -Compress")
    try:
        items = json.loads(out) if out else []
    except json.JSONDecodeError:
        return []
    items = items if isinstance(items, list) else [items]
    wins = {}
    for it in items:
        if it.get("p"):
            wins.setdefault(it["h"], []).append(it["p"])
    return list(wins.values())


def _shell_path(p):
    return "shell:" + p if p.startswith("::") else p


def _wait_explorer(timeout=20):
    """Ждать, пока поднимется панель задач нового Проводника."""
    import ctypes
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None):
            time.sleep(1.5)
            return True
        time.sleep(0.3)
    return False


RESTORE_PS = r"""
$wins = Get-Content -LiteralPath '{FILE}' -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type @'
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr p, IntPtr c, string cls, string t);
                 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l); }
'@
$s = New-Object -ComObject Shell.Application
function Tabs($h) { @($s.Windows() | ? { [int64]$_.HWND -eq $h }) }
foreach ($w in $wins) {
  $tabs = @($w)
  $before = @($s.Windows() | % { [int64]$_.HWND })
  Start-Process explorer.exe -ArgumentList ('"' + $tabs[0] + '"')
  $h = 0
  for ($i = 0; $i -lt 60 -and -not $h; $i++) { Start-Sleep -Milliseconds 150
    $n = @($s.Windows() | ? { $_.FullName -match 'explorer\.exe$' -and $before -notcontains [int64]$_.HWND }); if ($n) { $h = [int64]$n[0].HWND } }
  if (-not $h) { continue }
  for ($k = 1; $k -lt $tabs.Count; $k++) {
    $count = (Tabs $h).Count
    [W]::PostMessage([IntPtr]$h, 0x0111, [IntPtr]0xA21B, [IntPtr]::Zero) | Out-Null   # WM_COMMAND окну: новая вкладка
    for ($i = 0; $i -lt 40 -and (Tabs $h).Count -le $count; $i++) { Start-Sleep -Milliseconds 100 }
    $t = Tabs $h
    if ($t.Count -gt $count) { $t[$t.Count - 1].Navigate2($tabs[$k]) }
  }
}
"""


def restore_windows(wins):
    if not wins:
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE.replace(".json", "-restore.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([[_shell_path(p) for p in w] for w in wins], f, ensure_ascii=False)
    _ps(RESTORE_PS.replace("{FILE}", tmp.replace("'", "''")), timeout=180)


def restart_automates():
    if os.path.exists(AHK) and os.path.exists(AUTOMATES):           # /restart заменяет уже запущенную копию
        subprocess.Popen([AHK, "/restart", AUTOMATES], creationflags=NO_WINDOW)


def restart_explorer(automates=True):
    wins = save_windows()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(wins, f, ensure_ascii=False, indent=1)
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True, creationflags=NO_WINDOW)
    subprocess.Popen(["explorer.exe"])
    _wait_explorer()
    restore_windows(wins)
    if automates:
        restart_automates()
    return wins


if __name__ == "__main__":
    if "--save" in sys.argv:
        print(json.dumps(save_windows(), ensure_ascii=False, indent=1))
    elif "--restore" in sys.argv:
        restore_windows(json.load(open(sys.argv[sys.argv.index("--restore") + 1], encoding="utf-8")))
    else:
        restart_explorer(automates="--no-automates" not in sys.argv)

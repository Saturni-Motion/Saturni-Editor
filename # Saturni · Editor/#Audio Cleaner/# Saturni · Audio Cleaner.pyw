#!C:\Users\SATURNi\.stemstudio\venv\Scripts\pythonw.exe
# -*- coding: utf-8 -*-
# Saturni · Audio Cleaner: запуск в своей среде (первая строка — её pythonw, её читает pyw.exe).
import os
import runpy

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), run_name="__main__")

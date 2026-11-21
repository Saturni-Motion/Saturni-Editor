# -*- coding: utf-8 -*-
"""Subs Move теперь режим приложения Saturni · Subs (переключатель Studio | Move в шапке): запускает его."""
import os
import runpy
import sys

sys.argv = [sys.argv[0], "--move"] + sys.argv[1:]
runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "# Saturni · Subs.pyw"), run_name="__main__")

# -*- coding: utf-8 -*-
r"""Saturni · Editor, фото: качество JPEG при сохранении."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from common import *

def jpeg_quality(im) -> int:
    """The quality a JPEG was saved with, from its luminance table (IJG scaling): saving it back at
    the same quality keeps its size and look instead of inflating it."""
    std = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
           14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
           49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
    q = getattr(im, "quantization", None) or {}
    t = q.get(0)
    if not t:
        return 92
    scale = sum(t) / sum(std) * 100
    qual = (200 - scale) / 2 if scale <= 100 else 5000 / scale
    return int(max(50, min(100, round(qual))))

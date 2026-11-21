"""Neural separation models: Demucs (music stems) and BandIt Plus (speech / music / effects)."""
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import torch

from .paths import RUNTIME, MSST_DIR, MODELS_DIR

warnings.filterwarnings("ignore", message=".*ComplexHalf.*")
warnings.filterwarnings("ignore", category=FutureWarning)

SR = 44100
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_cache = {}


def _free_other(keep):
    for k in list(_cache):
        if k != keep:
            del _cache[k]
    if DEVICE.type == "cuda":
        torch.cuda.empty_cache()


# ---------------------------------------------------------------- Demucs

DEMUCS_NAMES = {"stems4": "htdemucs", "stems6": "htdemucs_6s", "vocals": "htdemucs"}


def demucs_separate(mix: np.ndarray, mode: str, progress) -> dict:
    """mix: (2, T) float32 at 44.1k. Returns {stem: (2, T)}."""
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    name = DEMUCS_NAMES[mode]
    key = "demucs:" + name
    _free_other(key)
    if key not in _cache:
        progress(0.02, "@load_model")
        torch.hub.set_dir(str(RUNTIME / "torch_hub"))
        m = get_model(name)
        m.to(DEVICE).eval()
        _cache[key] = m
    model = _cache[key]

    wav = torch.from_numpy(mix).float()
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std

    # apply_model reports progress through tqdm only; split into big pieces to report ourselves
    total = wav.shape[-1]
    piece = SR * 60
    outs = []
    for i, start in enumerate(range(0, total, piece)):
        # overlap pieces by 1 s to hide seams
        a = max(0, start - SR)
        b = min(total, start + piece + SR)
        with torch.no_grad():
            out = apply_model(model, wav[None, :, a:b], device=DEVICE, shifts=1,
                              split=True, overlap=0.25, progress=False)[0]
        out = out[:, :, start - a: start - a + min(piece, total - start)]
        outs.append(out.cpu())
        progress(0.05 + 0.9 * min(1.0, (start + piece) / total), "@splitting")
    out = torch.cat(outs, dim=-1) * std + mean
    stems = {s: out[i].numpy() for i, s in enumerate(model.sources)}
    if mode == "vocals":
        inst = sum(v for k, v in stems.items() if k != "vocals")
        stems = {"vocals": stems["vocals"], "instrumental": inst}
    return stems


# ---------------------------------------------------------------- BandIt Plus (DnR)

def _load_bandit():
    import yaml

    # Import only the model sub-package; the package __init__ pulls training deps we don't need.
    if str(MSST_DIR) not in sys.path:
        sys.path.insert(0, str(MSST_DIR))
    for pkg in ("models", "models.bandit", "models.bandit.core"):
        if pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__ = [str(MSST_DIR / Path(*pkg.split(".")))]
            sys.modules[pkg] = mod
    from models.bandit.core.model import MultiMaskMultiSourceBandSplitRNNSimple

    cfg = yaml.safe_load(open(MODELS_DIR / "config_dnr_bandit.yaml", encoding="utf-8"))
    model = MultiMaskMultiSourceBandSplitRNNSimple(**cfg["model"])
    state = torch.load(MODELS_DIR / "bandit_plus_dnr.chpt", map_location="cpu", weights_only=False)
    for k in ("state", "state_dict", "model_state_dict"):
        if isinstance(state, dict) and k in state:
            state = state[k]
    model.load_state_dict(state)
    model.to(DEVICE).eval()
    return model, cfg


def bandit_separate(mix: np.ndarray, progress, p0=0.0, p1=1.0) -> dict:
    """mix: (2, T) at 44.1k → {'speech','music','effects': (2, T)}."""
    _free_other("bandit")
    if "bandit" not in _cache:
        progress(p0, "@load_model")
        _cache["bandit"] = _load_bandit()
    model, cfg = _cache["bandit"]
    stems = cfg["model"]["stems"]

    chunk = cfg["audio"]["chunk_size"]
    step = chunk // 2
    fade = chunk // 10
    T = mix.shape[-1]
    pad = chunk
    x = np.pad(mix, ((0, 0), (pad, pad + chunk)), mode="constant")
    win = np.ones(chunk, dtype=np.float32)
    win[:fade] = np.linspace(0, 1, fade)
    win[-fade:] = np.linspace(1, 0, fade)
    win_t = torch.from_numpy(win).to(DEVICE)

    xt = torch.from_numpy(x).float().to(DEVICE)
    out = torch.zeros((len(stems),) + xt.shape, device=DEVICE)
    cnt = torch.zeros(xt.shape[-1], device=DEVICE)
    starts = list(range(0, x.shape[-1] - chunk + 1, step))
    with torch.inference_mode(), torch.autocast(DEVICE.type, enabled=DEVICE.type == "cuda"):
        for i, s in enumerate(starts):
            seg = xt[:, s:s + chunk]
            if seg.abs().mean() < 1e-6:
                continue
            y = model(seg[None])[0].float()  # (stems, C, chunk)
            out[:, :, s:s + chunk] += y * win_t
            cnt[s:s + chunk] += win_t
            if i % 4 == 0:
                progress(p0 + (p1 - p0) * (i + 1) / len(starts), "@separate")
    out = out / cnt.clamp(min=1e-3)
    out = out[:, :, pad:pad + T].cpu().numpy()
    return {s: out[i] for i, s in enumerate(stems)}

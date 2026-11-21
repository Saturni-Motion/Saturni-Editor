"""Reference matching that tolerates a different copy of the song (other digitisation, master or encode).

Exact waveform subtraction (refmatch.py) needs the very same file. When the song in the recording
comes from another copy, the waveforms differ but the spectrogram — which notes sound when — is the
same. Here the reference is aligned by its log-mel spectrogram (montage cuts and jumps included,
slow speed drift too), and its aligned magnitude then tells which part of the neural "music" stem
really is this song. Everything the song does not explain (room noise, background talk) stays.
"""
import numpy as np
import torch
import torchaudio
from scipy.ndimage import maximum_filter, median_filter

SR = 44100
FPS = 100
HOP_F = SR // FPS            # 441 samples per feature frame
W = 300                      # 3 s analysis window
STEP = 50                    # 0.5 s between windows
TOPK = 6
NULL_SCORE = 0.40            # score of "no song here"
JUMP = 0.12                  # cost of a montage jump
DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_mel = None


def features(x: np.ndarray) -> torch.Tensor:
    """(2,T) or (T,) at 44.1k → per-band-normalised log-mel (96, frames) at 100 fps."""
    global _mel
    if _mel is None:
        _mel = torchaudio.transforms.MelSpectrogram(SR, n_fft=4096, hop_length=HOP_F, n_mels=96,
                                                    f_min=60, f_max=8000).to(DEV)
    mono = x.mean(0) if x.ndim == 2 else x
    S = torch.log(_mel(torch.from_numpy(np.ascontiguousarray(mono)).to(DEV)) + 1e-5)
    return S - S.mean(1, keepdim=True)


def _scan(A: torch.Tensor, B: torch.Tensor):
    """For every window of A: top-K (score, lag) of normalised cross-correlation against B."""
    T = B.shape[1]
    if T <= W + 1 or A.shape[1] <= W:
        return np.zeros((0,)), np.zeros((0, TOPK)), np.zeros((0, TOPK), int)
    n = 1 << int(np.ceil(np.log2(T + W)))
    FB = torch.fft.rfft(B, n)
    e = torch.cumsum(torch.cat([torch.zeros(1, device=DEV), (B ** 2).sum(0)]), 0)
    eB = (e[W:] - e[:-W])[: T - W]
    starts = np.arange(0, A.shape[1] - W, STEP)
    scores = np.zeros((len(starts), TOPK))
    lags = np.zeros((len(starts), TOPK), int)
    bs = max(1, int(2 ** 26 // (n * 96)))
    for b0 in range(0, len(starts), bs):
        idx = starts[b0:b0 + bs]
        a = torch.stack([A[:, s:s + W] for s in idx])                        # (b, 96, W)
        c = torch.fft.irfft(torch.conj(torch.fft.rfft(a, n)) * FB[None], n).sum(1)[:, : T - W]
        c = c / torch.sqrt(eB[None] * (a ** 2).sum((1, 2))[:, None] + 1e-9)
        for k in range(TOPK):  # peak picking with ±0.5 s suppression
            pk, lg = c.max(1)
            scores[b0:b0 + len(idx), k] = pk.cpu().numpy()
            lags[b0:b0 + len(idx), k] = lg.cpu().numpy()
            ar = torch.arange(c.shape[1], device=DEV)[None]
            c = c.masked_fill((ar - lg[:, None]).abs() < 50, -1)
    return starts, scores, lags


def _viterbi(starts, scores, lags):
    """Best path through candidates (or 'no song'), cheap to continue, costly to jump."""
    nW = len(starts)
    if nW == 0:
        return []
    off = starts[:, None] - lags                                    # offset in frames (mix - ref)
    S = np.concatenate([scores, np.full((nW, 1), NULL_SCORE)], 1)  # last state = no song
    K = S.shape[1]
    acc = S[0].copy()
    back = np.zeros((nW, K), int)
    for i in range(1, nW):
        new = np.empty(K)
        for k in range(K):
            if k == K - 1:
                trans = acc.copy()
                trans[:-1] -= JUMP * 0.5
            else:
                same = np.abs(off[i - 1] - off[i, k]) <= 15
                trans = acc.copy()
                trans[:-1] -= np.where(same, 0.0, JUMP)
                trans[-1] -= JUMP * 0.5
            back[i, k] = int(np.argmax(trans))
            new[k] = trans[back[i, k]] + S[i, k]
        acc = new
    path = [int(np.argmax(acc))]
    for i in range(nW - 1, 0, -1):
        path.append(back[i, path[-1]])
    path = path[::-1]
    return [(int(off[i, k]), float(scores[i, k])) if k < TOPK else None for i, k in enumerate(path)]


def match(music_feat: torch.Tensor, ref: np.ndarray, total_frames: int):
    """→ segments [{a, b (frames), off0, slope, score}] where the reference plays."""
    B = features(ref)
    starts, scores, lags = _scan(music_feat, B)
    path = _viterbi(starts, scores, lags)
    segs, cur = [], None
    for i, p in enumerate(path):
        c = starts[i] + W // 2
        if p is not None and cur is not None and abs(p[0] - cur["pts"][-1][1]) <= 15:
            cur["pts"].append((c, p[0], p[1]))
        else:
            if cur:
                segs.append(cur)
            cur = {"pts": [(c, p[0], p[1])]} if p is not None else None
    if cur:
        segs.append(cur)
    out = []
    for s in segs:
        pts = np.array(s["pts"], float)
        if len(pts) < 2 and pts[0, 2] < 0.55:
            continue
        if len(pts) >= 4:
            slope, off0 = np.polyfit(pts[:, 0], pts[:, 1], 1)
            if abs(slope) > 0.01:
                slope, off0 = 0.0, float(np.median(pts[:, 1]))
        else:
            slope, off0 = 0.0, float(np.median(pts[:, 1]))
        a = int(pts[0, 0] - STEP // 2)
        b = int(pts[-1, 0] + STEP // 2)
        out.append({"a": a, "b": b, "off0": float(off0), "slope": float(slope),
                    "score": float(pts[:, 2].mean()), "n": len(pts)})
    # windows are 3 s long: extend outer edges that border silence/no-song by the half window
    for i, s in enumerate(out):
        if i == 0 or out[i - 1]["b"] < s["a"] - STEP:
            s["a"] = max(0, s["a"] - (W // 2 - STEP // 2))
        if i == len(out) - 1 or out[i + 1]["a"] > s["b"] + STEP:
            s["b"] = min(total_frames, s["b"] + (W // 2 - STEP // 2))
    return out


def coverage(segs):
    return sum(s["b"] - s["a"] for s in segs) / FPS


# ------------------------------------------------------------------ reference-guided music estimate

N_FFT = 4096
HOP = 1024


def _spec(x):
    return torch.stft(torch.from_numpy(np.ascontiguousarray(x)).to(DEV), N_FFT, HOP,
                      window=torch.hann_window(N_FFT, device=DEV), return_complex=True)


def song_from_music(music_nn: np.ndarray, refs: dict, matches: dict, margin=1.6):
    """Keep only the part of the neural music stem that the aligned references explain.

    music_nn: (2,T); refs: {rid: (2,Tr)}; matches: {rid: [segments]} → (song (2,T), active (T,) bool)."""
    T = music_nn.shape[-1]
    M = _spec(music_nn)                                  # (2, F, N)
    Mm = M.abs().mean(0)                                 # (F, N)
    Fq, N = Mm.shape
    pred = torch.zeros_like(Mm)
    active = np.zeros(T, bool)
    t_frames = np.arange(N) * HOP / SR * FPS             # stft frame → feature-frame time
    for rid, segs in matches.items():
        if not segs:
            continue
        R = _spec(refs[rid].mean(0)).abs()               # (F, Nr)
        Nr = R.shape[1]
        for s in segs:
            sel = np.where((t_frames >= s["a"]) & (t_frames < s["b"]))[0]
            if not len(sel):
                continue
            tf = t_frames[sel]
            ref_t = (tf - (s["off0"] + s["slope"] * tf)) / FPS * SR / HOP   # ref stft frame (float)
            ok = (ref_t >= 0) & (ref_t < Nr - 1)
            sel, ref_t = sel[ok], ref_t[ok]
            if not len(sel):
                continue
            i0 = torch.from_numpy(np.floor(ref_t).astype(np.int64)).to(DEV)
            w = torch.from_numpy((ref_t - np.floor(ref_t)).astype(np.float32)).to(DEV)
            Ra = R[:, i0] * (1 - w) + R[:, i0 + 1] * w
            idx = torch.from_numpy(sel).to(DEV)
            pred[:, idx] = torch.maximum(pred[:, idx], Ra)
            active[int(s["a"] / FPS * SR):int(s["b"] / FPS * SR)] = True
    if not active.any():
        return np.zeros_like(music_nn), active

    # tolerate small timing/pitch differences between copies
    P = torch.from_numpy(maximum_filter(pred.cpu().numpy(), size=(3, 3))).to(DEV)
    # gain per frequency band and time: robust median of stem / reference
    edges = np.unique(np.geomspace(4, Fq, 33).astype(int))
    G = torch.zeros_like(P)
    for lo, hi in zip(edges[:-1], edges[1:]):
        r = Mm[lo:hi] / (P[lo:hi] + 1e-7)
        strong = P[lo:hi] > P[lo:hi].mean() * 0.3
        r = torch.where(strong, r, torch.nan)
        g = torch.nanmedian(r, 0).values.cpu().numpy()
        g = np.nan_to_num(g, nan=0.0)
        g = median_filter(g, size=int(2.0 * SR / HOP) | 1)
        G[lo:hi] = torch.from_numpy(g.astype(np.float32)).to(DEV)[None]
    mask = (margin * G * P / (Mm + 1e-7)).clamp(0, 1)
    song = torch.istft(M * mask[None], N_FFT, HOP, window=torch.hann_window(N_FFT, device=DEV), length=T)
    return song.cpu().numpy(), active

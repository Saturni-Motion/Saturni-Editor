"""Find where reference songs play inside a mix (including montage cuts and jumps) and subtract them.

1. Coarse detection: the mix is cut into short windows; each window is matched against the
   whole reference with GCC-PHAT cross-correlation (robust to EQ, volume and talking over it).
   Every distinct (song, time offset) pair that is found becomes a candidate.
2. Fine assignment: each candidate is aligned sample-accurately and compared with the mix in
   50 ms steps, so cuts and jumps between song parts get sharp boundaries.
3. Subtraction: inside its active span each candidate drives an adaptive, slowly time-varying
   linear filter (per STFT bin and channel, least squares) that follows volume ducking, fades,
   EQ and panning. Only what this filter explains is removed — everything else stays.
"""
import numpy as np
import torch
from scipy.ndimage import binary_closing, binary_opening
from scipy.signal import resample_poly

SR = 44100
DSR = 8000
WIN_S = 3.0
HOP_S = 1.0
Z_STRONG = 12.0   # window accepted on its own
Z_WEAK = 7.0      # accepted if a neighbour agrees on the offset
DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _down(x: np.ndarray) -> np.ndarray:
    mono = x.mean(0) if x.ndim == 2 else x
    return resample_poly(mono, 80, 441).astype(np.float32)  # 44100 → 8000


# ------------------------------------------------------------------ 1. coarse detection

def _coarse(m: np.ndarray, r: np.ndarray, starts, win, loud, progress=None):
    n = int(2 ** np.ceil(np.log2(len(r) + win)))
    R = torch.fft.rfft(torch.from_numpy(r).to(DEV), n)
    f = torch.fft.rfftfreq(n, 1 / DSR, device=DEV)
    band = ((f > 120) & (f < 3800))[None]
    hann = torch.hann_window(win, device=DEV)
    lag = np.zeros(len(starts), int)
    z = np.zeros(len(starts))
    bs = max(1, int(2 ** 25 // n))
    for b0 in range(0, len(starts), bs):
        c = torch.from_numpy(np.stack([m[s:s + win] for s in starts[b0:b0 + bs]])).to(DEV) * hann
        C = torch.conj(torch.fft.rfft(c, n)) * R[None]
        C = C / (C.abs() + 1e-9) * band
        corr = torch.fft.irfft(C, n)[:, : max(1, len(r) - win // 2)]
        pk, lg = corr.max(1)
        med = corr.median(1).values
        mad = (corr - med[:, None]).abs().median(1).values * 1.4826 + 1e-12
        lag[b0:b0 + bs] = lg.cpu().numpy()
        z[b0:b0 + bs] = ((pk - med) / mad).cpu().numpy()
        if progress:
            progress(min(1.0, (b0 + bs) / len(starts)))
    z[~loud] = 0
    return lag, z


def detect(mix: np.ndarray, refs: dict, progress=None) -> dict:
    """mix: (2, T) at 44.1k; refs: {ref_id: (2, Tr)}. Returns {ref_id: [segment, …]} (coarse)."""
    m = _down(mix)
    win, hop = int(WIN_S * DSR), int(HOP_S * DSR)
    starts = list(range(0, max(1, len(m) - win + 1), hop))
    rms = np.array([np.sqrt((m[s:s + win] ** 2).mean()) for s in starts])
    loud = rms > max(1e-4, np.median(rms) * 0.05)

    out = {}
    for ri, (rid, ref) in enumerate(refs.items()):
        lag, z = _coarse(m, _down(ref), starts, win, loud,
                         (lambda p, ri=ri: progress((ri + p) / len(refs))) if progress else None)
        off = np.array(starts) / DSR - lag / DSR  # mix_t - ref_t
        ok = z >= Z_STRONG
        for i in range(len(z)):
            if z[i] >= Z_WEAK and not ok[i]:
                for j in (i - 2, i - 1, i + 1, i + 2):
                    if 0 <= j < len(z) and z[j] >= Z_WEAK and abs(off[j] - off[i]) < 0.02:
                        ok[i] = True
        segs = []
        for i in np.where(ok)[0]:
            t0, t1 = starts[i] / DSR, starts[i] / DSR + WIN_S
            same = [s for s in segs if abs(s["offset"] - off[i]) < 0.02 and t0 <= s["mix_end"] + HOP_S]
            if same:
                same[-1]["mix_end"] = t1
                same[-1]["z"].append(float(z[i]))
            else:
                segs.append({"offset": float(off[i]), "mix_start": t0, "mix_end": t1, "z": [float(z[i])]})
        for s in segs:
            s["ref_start"] = s["mix_start"] - s["offset"]
            s["confidence"] = float(min(1.0, np.median(s["z"]) / 25))
            del s["z"]
        out[rid] = sorted(segs, key=lambda s: s["mix_start"])
    return out


# ------------------------------------------------------------------ 2. fine assignment

FRAME = int(0.4 * SR)
STEP = int(0.05 * SR)
C_HI, C_LO = 0.07, 0.03


def _refine_offset(mix_m, ref_m, off_s, t0, t1):
    """Sample-accurate offset around the coarse estimate (±5 ms)."""
    a = int(max(t0, off_s, 0) * SR)
    b = min(int(t1 * SR), a + 8 * SR, len(mix_m))
    seg = mix_m[a:b]
    span = 220
    ra = a - int(round(off_s * SR)) - span
    rb = ra + len(seg) + 2 * span
    if ra < 0 or rb > len(ref_m) or len(seg) < SR // 2:
        return off_s
    r = ref_m[ra:rb]
    n = int(2 ** np.ceil(np.log2(len(r) + len(seg))))
    C = np.conj(np.fft.rfft(seg, n)) * np.fft.rfft(r, n)
    c = np.fft.irfft(C / (np.abs(C) + 1e-9), n)[: 2 * span + 1]
    return off_s - (int(np.argmax(c)) - span) / SR


def _frame_sums(x):
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    idx = np.arange(0, len(x) - FRAME + 1, STEP)
    return c[idx + FRAME] - c[idx]


def assign(mix: np.ndarray, refs: dict, found: dict):
    """Turn coarse segments into candidates with exact per-50 ms activity.

    Returns a list of spans: {rid, offset, a, b} in samples (mix timeline)."""
    T = mix.shape[-1]
    pre = lambda x: np.diff(x, prepend=x[:1]).astype(np.float32)  # pre-emphasis: favour detail over bass
    mm = pre(mix.mean(0))
    em = _frame_sums(mm.astype(np.float64) ** 2)
    nF = len(em)

    cands = []
    for rid, segs in found.items():
        ref_m = refs[rid].mean(0)
        for s in segs:
            off = _refine_offset(mix.mean(0), ref_m, s["offset"], s["mix_start"], s["mix_end"])
            if any(c["rid"] == rid and abs(c["offset"] - off) < 0.003 for c in cands):
                continue
            cands.append({"rid": rid, "offset": off, "ref_m": None})
    if not cands:
        return []

    score = np.zeros((len(cands), nF), np.float32)
    for k, c in enumerate(cands):
        ref = refs[c["rid"]].mean(0)
        o = int(round(c["offset"] * SR))
        r = np.zeros(T, np.float32)
        a, b = max(0, o), min(T, o + len(ref))
        if b <= a:
            continue
        r[a:b] = ref[a - o:b - o]
        r = pre(r)
        er = _frame_sums(r.astype(np.float64) ** 2)
        x = _frame_sums(mm.astype(np.float64) * r)
        score[k] = np.where(er > 1e-9, x / np.sqrt(em * er + 1e-12), 0)

    best = score.max(0)
    spans = []
    close = int(1.0 * SR / STEP)
    for k, c in enumerate(cands):
        s = score[k]
        hi = (s > C_HI) & (s >= 0.5 * best)
        lo = (s > C_LO) & (s >= 0.4 * best)
        act = binary_closing(lo, np.ones(close)) & lo | hi
        # hysteresis: keep low-score runs only if they touch a high-score frame
        lab = np.zeros_like(act)
        i = 0
        while i < nF:
            if act[i]:
                j = i
                while j < nF and act[j]:
                    j += 1
                if hi[i:j].any():
                    lab[i:j] = True
                i = j
            else:
                i += 1
        lab = binary_opening(lab, np.ones(10))  # drop blips shorter than ~0.5 s
        i = 0
        while i < nF:
            if lab[i]:
                j = i
                while j < nF and lab[j]:
                    j += 1
                # frame centres → samples; a frame covers [i*STEP, i*STEP+FRAME)
                a = i * STEP + FRAME // 2 - STEP
                b = (j - 1) * STEP + FRAME // 2 + STEP
                spans.append({"rid": c["rid"], "offset": c["offset"], "a": max(0, a), "b": min(T, b)})
                i = j
            else:
                i += 1
    return spans


def spans_to_segments(spans: dict | list):
    """Spans (samples) → UI segments (seconds), per reference."""
    out = {}
    for s in spans:
        if s["b"] - s["a"] < SR:  # too short to be worth showing
            continue
        out.setdefault(s["rid"], []).append({
            "mix_start": s["a"] / SR, "mix_end": s["b"] / SR,
            "ref_start": s["a"] / SR - s["offset"], "offset": s["offset"]})
    for v in out.values():
        v.sort(key=lambda s: s["mix_start"])
    return out


# ------------------------------------------------------------------ 3. subtraction

N_FFT = 4096
HOP = 1024
SMOOTH_S = 1.5
LEAK = 0.12     # expected leftover of the song after subtraction (power ratio), removed by a gentle post-filter
FADE = int(0.02 * SR)


def _stft(x):
    return torch.stft(x, N_FFT, HOP, window=torch.hann_window(N_FFT, device=x.device), return_complex=True)


def _istft(X, length):
    return torch.istft(X, N_FFT, HOP, window=torch.hann_window(N_FFT, device=X.device), length=length)


def subtract(mix: np.ndarray, refs: dict, spans: list, progress=None):
    """Returns (rest (2,T) — everything except the songs, song (2,T), active mask (T,) bool)."""
    T = mix.shape[-1]
    active = np.zeros(T, bool)
    tracks = []
    for s in spans:
        ref = refs[s["rid"]]
        o = int(round(s["offset"] * SR))
        a, b = max(s["a"], o), min(s["b"], o + ref.shape[-1])
        if b - a < SR // 4:
            continue
        active[a:b] = True
        pa, pb = max(0, a - N_FFT), min(T, b + N_FFT)
        tr = np.zeros((2, pb - pa), np.float32)
        tr[:, a - pa:b - pa] = ref[:, a - o:b - o]
        f = min(FADE, (b - a) // 4)
        tr[:, a - pa:a - pa + f] *= np.linspace(0, 1, f)
        tr[:, b - pa - f:b - pa] *= np.linspace(1, 0, f)
        fa = pa // HOP
        lead = pa - fa * HOP
        spec = _stft(torch.from_numpy(np.pad(tr, ((0, 0), (lead, 0)))))
        tracks.append((spec, fa))
    if not tracks:
        return mix.copy(), np.zeros_like(mix), active

    X = _stft(torch.from_numpy(mix))
    Fq, N = X.shape[-2:]
    out = X.clone()
    fps = SR / HOP
    smooth = int(SMOOTH_S * fps) | 1
    kern = torch.hann_window(smooth + 2, device=DEV)[1:-1]
    kern = (kern / kern.sum())[None, None]

    def block_of(spec, f0, a0, a1):
        z = torch.zeros((2, Fq, a1 - a0), dtype=X.dtype)
        s0, s1 = max(a0, f0), min(a1, f0 + spec.shape[-1])
        if s1 > s0:
            z[:, :, s0 - a0:s1 - a0] = spec[:, :, s0 - f0:s1 - f0]
        return z

    def sm(z):  # smooth along time and ±1 bin in frequency
        sh = z.shape
        zr = z.reshape(-1, 1, sh[-1])
        re = torch.nn.functional.conv1d(zr.real, kern, padding=smooth // 2)
        im = torch.nn.functional.conv1d(zr.imag, kern, padding=smooth // 2)
        z = torch.complex(re, im).reshape(sh)
        return (z + torch.roll(z, 1, -2) + torch.roll(z, -1, -2)) / 3

    def solve(Rm, Xb):
        M = Rm.shape[0]
        A = sm(Rm[:, None].conj() * Rm[None]).permute(2, 3, 0, 1)   # (F, n, M, M)
        B = sm(Rm[None].conj() * Xb[:, None]).permute(2, 3, 1, 0)   # (F, n, M, 2)
        lam = 1e-3 * torch.diagonal(A, dim1=-2, dim2=-1).real.mean(-1, keepdim=True) + 1e-10
        A = A + torch.diag_embed(lam.expand(-1, -1, M)).to(A.dtype)
        G = torch.linalg.solve(A, B)
        Y = torch.einsum("fnmc,mfn->cfn", G, Rm)                      # song estimate
        Rz = Xb - Y
        # gentle post-filter: suppress only the expected leftover of the song
        pr = torch.nn.functional.avg_pool1d((Rz.abs() ** 2).reshape(-1, 1, Rz.shape[-1]), 3, 1, 1).reshape(Rz.shape)
        g = (1 - LEAK * Y.abs() ** 2 / (pr + 1e-12)).clamp(min=0.15) ** 0.5
        return Rz * g

    blk = int(6 * fps)
    for b0 in range(0, N, blk):
        b1 = min(N, b0 + blk)
        a0, a1 = max(0, b0 - smooth), min(N, b1 + smooth)
        act = [t for t in tracks if t[1] < a1 and t[1] + t[0].shape[-1] > a0]
        if not act:
            continue
        Rm_all = torch.cat([block_of(sp, f0, a0, a1) for sp, f0 in act], 0)  # (M, F, n) on CPU
        M = Rm_all.shape[0]
        # frequency chunks keep GPU memory bounded when several song parts overlap
        fc = max(64, int(2.5e8 / (8 * M * M * (a1 - a0) * 6)))
        s0, s1 = b0 - a0, b1 - a0
        for q0 in range(0, Fq, fc):
            q1 = min(Fq, q0 + fc)
            e0, e1 = max(0, q0 - 1), min(Fq, q1 + 1)
            res = solve(Rm_all[:, e0:e1].to(DEV), X[:, e0:e1, a0:a1].to(DEV))
            out[:, q0:q1, b0:b1] = res[:, q0 - e0:q0 - e0 + (q1 - q0), s0:s1].cpu()
            del res
        if progress:
            progress(min(1.0, b1 / N))
    if DEV.type == "cuda":
        torch.cuda.empty_cache()

    rest = _istft(out, T).numpy()
    return rest, mix - rest, active


def regions(mask: np.ndarray, min_len=0.0):
    """Boolean sample mask → [[t0, t1], …] seconds."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    a, b = np.where(d == 1)[0], np.where(d == -1)[0]
    return [[x / SR, y / SR] for x, y in zip(a, b) if (y - x) / SR >= min_len]


def music_regions(music: np.ndarray, rel_db=-30.0, min_len=1.5, win_s=0.5):
    """Where a (neural) music stem is clearly audible — boolean mask at sample rate."""
    win = int(win_s * SR)
    mono = music.mean(0)
    n = len(mono) // win
    e = np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(1) + 1e-12)
    ref = np.percentile(e, 95) + 1e-9
    on = 20 * np.log10(e / ref) > rel_db
    on = binary_closing(on, np.ones(int(2 / win_s)))
    on = binary_opening(on, np.ones(max(1, int(min_len / win_s))))
    mask = np.zeros(len(mono), bool)
    mask[: n * win] = np.repeat(on, win)
    return mask

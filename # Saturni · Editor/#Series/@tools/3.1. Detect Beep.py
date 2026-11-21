# -*- coding: utf-8 -*-
"""Detect a monotone censor-beep tone in speech audio via sliding-window FFT.
A beep concentrates almost all energy in a narrow band around one frequency;
speech never does (formants spread energy across many bands).

Validated 2026-09-04 on "Холод" Серия 8: found all 6 known bleeps (a 1000 Hz
tone) in clips 2 and 3 with exact-matching boundaries, zero false positives
across 5 control clips (incl. a noisy party scene that fooled an RMS-based
check earlier). Run on the ORIGINAL extracted audio (ffmpeg -vn -ac 1),
not the Demucs vocal stem — untested whether Demucs preserves/relocates
a bleep tone. Cross-reference results against gaps in words.json before
inserting "*****" into a caption — never insert blind.

Usage:
  ffmpeg -y -i video.mp4 -vn -ac 1 -ar 44100 audio.wav
  python 3.1. Detect Beep.py audio.wav
"""
import numpy as np, wave, sys

def load_wav(path):
    w = wave.open(path, 'rb')
    sr = w.getframerate()
    n = w.getnframes()
    data = w.readframes(n)
    w.close()
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0
    return audio, sr

def find_beeps(audio, sr, win_s=0.15, hop_s=0.05, band_hz=40,
               conc_thresh=0.85, peak_ratio_thresh=400, min_dur=0.35,
               freq_lo=150, freq_hi=6000, min_rms_db=-45):
    win = int(win_s*sr); hop = int(hop_s*sr)
    hann = np.hanning(win)
    flags = []
    times = []
    for start in range(0, len(audio)-win, hop):
        seg = audio[start:start+win]
        rms = np.sqrt(np.mean(seg**2)) + 1e-12
        rms_db = 20*np.log10(rms)
        t = start/sr
        if rms_db < min_rms_db:
            flags.append(False); times.append(t); continue
        spec = np.abs(np.fft.rfft(seg*hann))**2 + 1e-15
        freqs = np.fft.rfftfreq(win, 1/sr)
        mask = (freqs >= freq_lo) & (freqs <= freq_hi)
        if not mask.any():
            flags.append(False); times.append(t); continue
        sub = spec[mask]; subf = freqs[mask]
        peak_i = np.argmax(sub)
        peak_freq = subf[peak_i]
        amean = np.mean(sub)
        peak_ratio = sub[peak_i]/amean
        band = (subf > peak_freq-band_hz) & (subf < peak_freq+band_hz)
        conc = sub[band].sum()/sub.sum()
        is_beep = (conc > conc_thresh) and (peak_ratio > peak_ratio_thresh)
        flags.append(is_beep); times.append(t)
    # merge contiguous flagged windows
    regions = []
    i = 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j < len(flags) and flags[j]:
                j += 1
            t0, t1 = times[i], times[j-1]+win_s
            if t1-t0 >= min_dur:
                regions.append((t0, t1))
            i = j
        else:
            i += 1
    return regions

if __name__ == '__main__':
    audio, sr = load_wav(sys.argv[1])
    regions = find_beeps(audio, sr)
    print(f"найдено участков: {len(regions)}")
    for t0, t1 in regions:
        print(f"  {t0:7.3f} -- {t1:7.3f}  ({t1-t0:.2f}s)")

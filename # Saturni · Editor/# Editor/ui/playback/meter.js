// Level meter: true sample peaks, instant rise, 20 dB/s fall, peak hold 1.5 s.

// ---------- level meter: true sample peaks, instant rise, 20 dB/s fall, peak hold 1.5 s
const MDB = [12, 6, 0, -6, -12, -18, -24, -36, -48, -60, -72, -90];
let meterL = [-120, -120], holdV = [-120, -120], holdT = [0, 0], lastMT = 0;
function mLo() { return O.meterMin ?? -60; }
function mHi() { return O.meterMax ?? 6; }
function dbY(db, h) {                            // the bars: exactly the height of the tracks
  const top = RULER + 2, bot = h;
  return top + (1 - (clamp(db, mLo(), mHi()) - mLo()) / (mHi() - mLo())) * (bot - top);
}
function drawMeter() {
  const dpr = devicePixelRatio || 1, w = mt.clientWidth, h = mt.clientHeight, lo = mLo(), hi = mHi();
  if (mt.width !== Math.round(w * dpr) || mt.height !== Math.round(h * dpr)) { mt.width = Math.round(w * dpr); mt.height = Math.round(h * dpr); }
  mx.setTransform(dpr, 0, 0, dpr, 0, 0); mx.clearRect(0, 0, w, h);
  const now = performance.now(), dt = lastMT ? Math.min(.2, (now - lastMT) / 1000) : 0; lastMT = now;
  const pk = [-120, -120];
  if (an && playing) for (let c = 0; c < 2; c++) {
    an[c].getFloatTimeDomainData(mbuf); let m = 0;
    for (let i = 0; i < mbuf.length; i++) { const v = Math.abs(mbuf[i]); if (v > m) m = v; }
    pk[c] = m > 1e-6 ? 20 * Math.log10(m) : -120;
  }
  for (let c = 0; c < 2; c++) {
    meterL[c] = Math.max(pk[c], meterL[c] - 20 * dt);
    if (pk[c] >= holdV[c]) { holdV[c] = pk[c]; holdT[c] = now; } else if (now - holdT[c] > 1500) holdV[c] -= 20 * dt;
  }
  mx.font = "8px Inter, Segoe UI"; mx.textAlign = "right";
  const fmtDb = d => (d > 0 ? "+" : "") + d, top = dbY(hi, h), bot = dbY(lo, h);
  mx.fillStyle = hexA(C.text, .28); mx.fillText(fmtDb(hi), 16, top + 7); mx.fillText(fmtDb(lo), 16, bot - 1);   // the two ends: inside, at the very ends of the bars
  let lastY = top + 4;
  for (const db of MDB) {
    if (db >= hi || db <= lo) continue;
    const y = dbY(db, h); if (y - lastY < 9 || bot - y < 12) continue;
    mx.fillStyle = hexA(C.text, db === 0 ? .55 : .28); mx.fillText(fmtDb(db), 16, y + 3); lastY = y;
  }
  for (let c = 0; c < 2; c++) {
    const x = 18 + c * 6;
    mx.fillStyle = hexA(C.text, .06); mx.fillRect(x, top, 5, bot - top);
    const lv = meterL[c];
    if (lv > lo) for (const [a, b, col] of [[lo, -18, C.meterLow], [-18, -6, C.meterMid], [-6, hi, C.meterHigh]]) {
      if (lv <= a || b <= a) continue; const ya = dbY(Math.min(lv, b), h), yb = dbY(Math.max(a, lo), h); mx.fillStyle = col; mx.fillRect(x, ya, 5, yb - ya);
    }
    if (holdV[c] > lo) { mx.fillStyle = holdV[c] > -6 ? C.meterHigh : hexA(C.text, .7); mx.fillRect(x, Math.round(dbY(holdV[c], h)), 5, 1); }
  }
  return meterL[0] > lo || meterL[1] > lo || holdV[0] > lo || holdV[1] > lo;
}

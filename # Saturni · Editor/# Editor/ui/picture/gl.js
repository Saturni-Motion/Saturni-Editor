// WebGL preview: the same math as color_fn() / adjust_array() in Python.

// ---------- WebGL preview: the same math as color_fn() / adjust_array() in Python; keeps the last frame while a video seeks
let gl = null, glOk = false, glProg = null, glTex = null, glU = {}, glDirty = true, glSeed = 0, glHas = false, glSrc = null;
const VS = "attribute vec2 p; varying vec2 vUv; void main(){ vUv = vec2(p.x * .5 + .5, .5 - p.y * .5); gl_Position = vec4(p, 0., 1.); }";
const FS = `precision highp float;
varying vec2 vUv; uniform sampler2D T; uniform vec2 texel; uniform vec4 crop; uniform float seed;
uniform float uPlain, uHsl, uExp, uBri, uCon, uSat, uTemp, uTint, uHi, uSh, uWh, uBl, uSharp, uClar, uGrain, uNr, uVig, uDisp, clarR;
uniform float hH[8], hS[8], hL[8];
vec3 raw(vec2 uv) {
  if (uDisp <= 0.) return texture2D(T, uv).rgb;
  vec2 d = uv - .5;
  return vec3(texture2D(T, .5 + d * (1. + uDisp)).r, texture2D(T, uv).g, texture2D(T, .5 + d * (1. - uDisp)).b);
}
float ss(float a, float b, float x) { float t = clamp((x - a) / (b - a), 0., 1.); return t * t * (3. - 2. * t); }
vec3 rgb2hsl(vec3 c) {
  float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), l = (mx + mn) / 2., d = mx - mn, h = 0., s = 0.;
  if (d > 1e-6) {
    s = clamp(d / max(1e-6, 1. - abs(2. * l - 1.)), 0., 1.);
    if (mx == c.r) h = 60. * mod((c.g - c.b) / d, 6.); else if (mx == c.g) h = 60. * ((c.b - c.r) / d + 2.); else h = 60. * ((c.r - c.g) / d + 4.);
  }
  return vec3(h, s, l);
}
vec3 hsl2rgb(vec3 q) {
  float h = q.x, s = q.y, l = q.z, C = (1. - abs(2. * l - 1.)) * s, X = C * (1. - abs(mod(h / 60., 2.) - 1.)), m = l - C / 2.;
  float k = floor(mod(h, 360.) / 60.); vec3 c;
  if (k == 0.) c = vec3(C, X, 0.); else if (k == 1.) c = vec3(X, C, 0.); else if (k == 2.) c = vec3(0., C, X);
  else if (k == 3.) c = vec3(0., X, C); else if (k == 4.) c = vec3(X, 0., C); else c = vec3(C, 0., X);
  return c + m;
}
float hueAt(float h, float v[8]) {
  float c0 = 0., c1 = 30., a = v[0], b = v[1];
  if (h >= 300.) { c0 = 300.; c1 = 360.; a = v[7]; b = v[0]; }
  else if (h >= 270.) { c0 = 270.; c1 = 300.; a = v[6]; b = v[7]; }
  else if (h >= 240.) { c0 = 240.; c1 = 270.; a = v[5]; b = v[6]; }
  else if (h >= 180.) { c0 = 180.; c1 = 240.; a = v[4]; b = v[5]; }
  else if (h >= 120.) { c0 = 120.; c1 = 180.; a = v[3]; b = v[4]; }
  else if (h >= 60.) { c0 = 60.; c1 = 120.; a = v[2]; b = v[3]; }
  else if (h >= 30.) { c0 = 30.; c1 = 60.; a = v[1]; b = v[2]; }
  return mix(a, b, (h - c0) / (c1 - c0));
}
vec3 colorize(vec3 c) {
  vec3 lin = pow(max(c, 0.), vec3(2.2)) * vec3(exp(.25 * uTemp), exp(-.2 * uTint), exp(-.25 * uTemp)) * exp2(uExp);
  c = pow(clamp(lin, 0., 1.), vec3(1. / 2.2));
  c = pow(c, vec3(exp2(-uBri)));
  float L = dot(c, vec3(.2126, .7152, .0722));
  float L1 = L + .5 * ss(.5, 1., L) * (uHi > 0. ? uHi * (1. - L) : uHi * L) + .5 * (1. - ss(0., .5, L)) * (uSh > 0. ? uSh * (1. - L) : uSh * L);
  float blk = .15 * uBl, wht = 1. + .15 * uWh, L2 = blk + L1 * (wht - blk);
  c = clamp(c + (L2 - L), 0., 1.);
  c = clamp((c - .5) * (1. + uCon) + .5, 0., 1.);
  float s = 1. + uSat;
  c = clamp(vec3(dot(vec3(.213 + .787 * s, .715 - .715 * s, .072 - .072 * s), c), dot(vec3(.213 - .213 * s, .715 + .285 * s, .072 - .072 * s), c),
                 dot(vec3(.213 - .213 * s, .715 - .715 * s, .072 + .928 * s), c)), 0., 1.);
  if (uHsl > .5) {
    vec3 q = rgb2hsl(c);
    float dh = hueAt(q.x, hH), ds = hueAt(q.x, hS), dl = hueAt(q.x, hL);
    if (dh != 0. || ds != 0. || dl != 0.) {
      float s0 = q.y;
      q.x = mod(q.x + dh * 30., 360.); q.y = clamp(q.y * (1. + ds), 0., 1.);
      q.z = clamp(q.z + dl * .5 * s0 * (dl > 0. ? 1. - q.z : q.z), 0., 1.);
      c = clamp(hsl2rgb(q), 0., 1.);
    }
  }
  return c;
}
void main() {
  if (uPlain > .5) { gl_FragColor = vec4(texture2D(T, vUv).rgb, 1.); return; }     // no effects: nothing to compute
  vec2 uv = vUv; vec3 c = raw(uv);
  if (uNr > 0.) {
    vec3 b = c * 4.;
    b += 2. * (raw(uv + vec2(texel.x, 0.)) + raw(uv - vec2(texel.x, 0.)) + raw(uv + vec2(0., texel.y)) + raw(uv - vec2(0., texel.y)));
    b += raw(uv + texel) + raw(uv - texel) + raw(uv + vec2(texel.x, -texel.y)) + raw(uv + vec2(-texel.x, texel.y));
    c = mix(c, b / 16., uNr);
  }
  if (uClar != 0.) {
    float L = dot(c, vec3(.2126, .7152, .0722)), Lb = 0.;
    for (int i = 0; i < 12; i++) {
      float a = float(i) * .5236; vec2 o = vec2(cos(a), sin(a)) * texel * clarR * (i < 6 ? 1. : .5);
      Lb += dot(raw(uv + o), vec3(.2126, .7152, .0722));
    }
    c += uClar * .8 * (L - Lb / 12.);
  }
  if (uSharp > 0.) c = (1. + 4. * uSharp) * c - uSharp * (raw(uv + vec2(texel.x, 0.)) + raw(uv - vec2(texel.x, 0.)) + raw(uv + vec2(0., texel.y)) + raw(uv - vec2(0., texel.y)));
  c = colorize(clamp(c, 0., 1.));
  if (uVig > 0.) { vec2 p = (uv - crop.xy) / crop.zw; float r = length((p - .5) / .5) / 1.41421356; c *= 1. - uVig * clamp((r - .4) / .6, 0., 1.); }
  if (uGrain > 0.) c += uGrain * .2 * (fract(sin(dot(uv / texel + seed, vec2(12.9898, 78.233))) * 43758.5453) - .5);
  gl_FragColor = vec4(clamp(c, 0., 1.), 1.);
}`;
function initGL() {
  try {
    gl = $("glc").getContext("webgl", { premultipliedAlpha: false, antialias: false, preserveDrawingBuffer: true }); if (!gl) return;
    const sh = (t, src) => { const o = gl.createShader(t); gl.shaderSource(o, src); gl.compileShader(o); if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw gl.getShaderInfoLog(o); return o; };
    glProg = gl.createProgram(); gl.attachShader(glProg, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(glProg, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(glProg);
    if (!gl.getProgramParameter(glProg, gl.LINK_STATUS)) throw gl.getProgramInfoLog(glProg);
    gl.useProgram(glProg);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(glProg, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    glTex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, glTex);
    for (const [k, v] of [[gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    for (const n of ["T", "texel", "crop", "seed", "uPlain", "uHsl", "uExp", "uBri", "uCon", "uSat", "uTemp", "uTint", "uHi", "uSh", "uWh", "uBl", "uSharp", "uClar", "uGrain", "uNr", "uVig", "uDisp", "clarR", "hH", "hS", "hL"])
      glU[n] = gl.getUniformLocation(glProg, n);
    glOk = true; document.body.classList.add("gl");
  } catch (e) { console.warn("WebGL off:", e); glOk = false; }
}
let texW = 1, texH = 1, lastVT = -1, lastUp = 0, ADJ0S = JSON.stringify(ADJ0);
let glTried = false;
function renderGL(el) {      // the shaders compile on the first picture, after the window is up (~0.6 s; sound alone never needs them)
  if (!glOk) { if (!glTried && hasPic()) { glTried = true; setTimeout(initGL, 0); } return; }
  const cv = $("glc"), dpr = devicePixelRatio || 1;
  const q = kind === "photo" ? 1 : pvq, w = Math.max(1, Math.round(vr.w * dpr / q)), h = Math.max(1, Math.round(vr.h * dpr / q));   // 1/2, 1/4: fewer pixels through the effects
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; glDirty = true; }
  if (!el) { if (glHas || glSrc !== null) { gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT); glHas = false; glSrc = null; } return; }   // a gap: black
  const isImg = el.tagName === "IMG", ready = isImg ? el.complete && el.naturalWidth : el.readyState >= 2 && !el.seeking;
  let fresh = false;
  const due = playing ? performance.now() - lastUp > 900 / fpsOr30() : el.currentTime !== lastVT;   // playing: once per video frame, not per screen refresh
  if (ready && (isImg ? glSrc !== el : glSrc !== el || due)) {     // a new frame: upload it; otherwise keep the last one
    gl.bindTexture(gl.TEXTURE_2D, glTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, el);
    texW = el.videoWidth || el.naturalWidth; texH = el.videoHeight || el.naturalHeight; glHas = true; glSrc = el; lastVT = isImg ? -1 : el.currentTime; lastUp = performance.now(); fresh = true;
  }
  if (!glHas || (!fresh && !glDirty && !(playing && st.G.adj.grain))) return;
  const fit = Math.min(w / texW, h / texH), vw = Math.round(texW * fit), vh = Math.round(texH * fit);    // another shape than the canvas: black around it, like in the saved file
  gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT); gl.viewport((w - vw) >> 1, (h - vh) >> 1, vw, vh);
  const a = st.G.adj, c = cr();
  gl.uniform1i(glU.T, 0); gl.uniform2f(glU.texel, 1 / texW, 1 / texH);
  gl.uniform4f(glU.crop, c.x / CW, c.y / CH, c.w / CW, c.h / CH); gl.uniform1f(glU.seed, isImg ? 7 : (glSeed = (glSeed + 1) % 997));
  const n = { uExp: a.exp, uBri: a.bri / 100, uCon: a.con / 100, uSat: a.sat / 100, uTemp: a.temp / 100, uTint: a.tint / 100, uHi: a.hi / 100, uSh: a.sh / 100,
    uWh: a.wh / 100, uBl: a.bl / 100, uSharp: a.sharp / 100 * .5, uClar: a.clar / 100, uGrain: a.grain / 100, uNr: a.nr / 100, uVig: a.vig / 100 * .9,
    uDisp: a.disp / 100 * .01, clarR: Math.max(1, .006 * texW) };
  for (const k in n) gl.uniform1f(glU[k], n[k]);
  gl.uniform1f(glU.uPlain, JSON.stringify(a) === ADJ0S ? 1 : 0); gl.uniform1f(glU.uHsl, a.hsl.h.some(v => v) || a.hsl.s.some(v => v) || a.hsl.l.some(v => v) ? 1 : 0);
  gl.uniform1fv(glU.hH, a.hsl.h.map(v => v / 100)); gl.uniform1fv(glU.hS, a.hsl.s.map(v => v / 100)); gl.uniform1fv(glU.hL, a.hsl.l.map(v => v / 100));
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); glDirty = false;
}

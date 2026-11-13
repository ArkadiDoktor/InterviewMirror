// InterviewMirror talking avatar.
//
// Turns one still portrait into a live "video call" tile, entirely in the
// browser and at zero cost: the photo is drawn as a WebGL mesh built from face
// landmarks (see tools/build_avatar_mesh.py); the mouth follows the loudness
// and brightness of the interviewer's voice, the eyes blink, and the head
// moves a little the way a person on a call does.
//
// Streamlit calls the default export once when the component mounts and again
// every time its `data` changes, with the same parentElement.

const FACE_TRIS = __FACE_TRIS__;

const LIP_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308];
const LIP_LO = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308];
const OUT_UP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291];
const EYES = [
  { up: [33, 246, 161, 160, 159, 158, 157, 173, 133], lo: [33, 7, 163, 144, 145, 153, 154, 155, 133] },
  { up: [263, 466, 388, 387, 386, 385, 384, 398, 362], lo: [263, 249, 390, 373, 374, 380, 381, 382, 362] },
];
const BROWS = [70, 63, 105, 66, 107, 300, 293, 334, 296, 336];
const N_LM = 478;
const N_FACE = 468;

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (a, b, v) => {
  const t = clamp((v - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};
const rand = (a, b) => a + Math.random() * (b - a);

const VERT = `
attribute vec2 aPos; attribute vec2 aUv; attribute vec3 aMouth;
uniform vec2 uSize; varying vec2 vUv; varying vec3 vMouth;
void main() {
  vUv = aUv; vMouth = aMouth;
  vec2 p = aPos / uSize * 2.0 - 1.0;
  gl_Position = vec4(p.x, -p.y, 0.0, 1.0);
}`;

const FRAG = `
precision mediump float;
varying vec2 vUv; varying vec3 vMouth;
uniform sampler2D uTex; uniform float uOpen;
void main() {
  vec4 photo = texture2D(uTex, vUv);
  if (vMouth.z < 0.5) { gl_FragColor = photo; return; }
  float u = vMouth.x, v = vMouth.y;
  float side = smoothstep(0.0, 0.3, u) * smoothstep(1.0, 0.7, u);
  vec3 cavity = vec3(0.16, 0.07, 0.07);
  vec3 tongue = vec3(0.42, 0.19, 0.2);
  vec3 teeth = vec3(0.7, 0.66, 0.62) * (0.55 + 0.45 * side);
  vec3 c = mix(cavity, tongue, smoothstep(0.5, 0.95, v) * side * 0.6);
  float band = smoothstep(0.0, 0.1, v) * (1.0 - smoothstep(0.2, 0.42, v));
  c = mix(c, teeth, band * side * smoothstep(0.18, 0.6, uOpen) * 0.85);
  c *= 0.62 + 0.38 * smoothstep(0.0, 0.25, v) * (1.0 - 0.35 * smoothstep(0.75, 1.0, v));
  c = mix(photo.rgb * 0.45, c, smoothstep(0.0, 0.12, v) * smoothstep(1.0, 0.9, v));
  gl_FragColor = vec4(mix(photo.rgb, c, smoothstep(0.03, 0.14, uOpen)), 1.0);
}`;

// ---------------------------------------------------------------- face model
function buildModel(mesh) {
  const lm = mesh.lm, ex = mesh.extra;
  const nExtra = ex.length / 3;
  const nCtl = N_LM + nExtra;
  const rx = new Float32Array(nCtl), ry = new Float32Array(nCtl);
  const depth = new Float32Array(nCtl), follow = new Float32Array(nCtl);
  let zMin = Infinity, zMax = -Infinity;
  for (let i = 0; i < N_FACE; i++) { const z = lm[i * 3 + 2]; zMin = Math.min(zMin, z); zMax = Math.max(zMax, z); }
  for (let i = 0; i < N_LM; i++) {
    rx[i] = lm[i * 3]; ry[i] = lm[i * 3 + 1];
    depth[i] = clamp((zMax - lm[i * 3 + 2]) / (zMax - zMin || 1), 0, 1);
    follow[i] = 1;
  }
  for (let j = 0; j < nExtra; j++) {
    rx[N_LM + j] = ex[j * 3]; ry[N_LM + j] = ex[j * 3 + 1];
    follow[N_LM + j] = ex[j * 3 + 2]; depth[N_LM + j] = 0.12;
  }

  const faceW = Math.abs(rx[454] - rx[234]);
  const cx = (rx[454] + rx[234]) / 2, cy = (ry[10] + ry[152]) / 2;
  const mcx = (rx[61] + rx[291]) / 2, mouthW = Math.abs(rx[291] - rx[61]), halfM = mouthW / 2;
  const seamY = (ry[13] + ry[14]) / 2, chinY = ry[152];

  const seamAt = (x) => {  // y of the lip seam under any x
    const pts = LIP_LO.map((i) => [rx[i], ry[i]]).sort((a, b) => a[0] - b[0]);
    if (x <= pts[0][0]) return pts[0][1];
    for (let k = 1; k < pts.length; k++) {
      if (x <= pts[k][0]) {
        const t = (x - pts[k - 1][0]) / (pts[k][0] - pts[k - 1][0] || 1);
        return pts[k - 1][1] + t * (pts[k][1] - pts[k - 1][1]);
      }
    }
    return pts[pts.length - 1][1];
  };

  // How much each landmark follows the jaw (down) and the upper lip (up).
  const jaw = new Float32Array(N_LM), lipUp = new Float32Array(N_LM);
  const inUp = new Set(LIP_UP), inLo = new Set(LIP_LO), outUp = new Set(OUT_UP);
  for (let i = 0; i < N_FACE; i++) {
    const u = Math.abs(rx[i] - mcx) / halfM;
    const lateralLip = 1 - smooth(0.5, 1.0, u);
    if (inLo.has(i)) { jaw[i] = lateralLip; continue; }
    if (inUp.has(i)) { lipUp[i] = lateralLip; continue; }
    if (outUp.has(i)) { lipUp[i] = 0.55 * lateralLip; continue; }
    const t = (ry[i] - seamAt(rx[i])) / (chinY - seamY);
    if (t <= 0) {
      if (t > -0.28 && u < 1.3) lipUp[i] = 0.3 * (1 - smooth(0.5, 1.3, u)) * (1 - smooth(0, 0.28, -t));
      continue;
    }
    jaw[i] = smooth(-0.02, 0.07, t) * (1 - smooth(0.55, 1.0 + 1.5 * t, u));
  }

  // Mouth corners: used for smiling, widening ("ee") and rounding ("oo").
  const cornerX = new Float32Array(N_LM), cornerW = new Float32Array(N_LM);
  for (const c of [61, 291]) {
    const sign = Math.sign(rx[c] - mcx), R = 0.62 * mouthW;
    for (let i = 0; i < N_FACE; i++) {
      const d = Math.hypot(rx[i] - rx[c], ry[i] - ry[c]);
      if (d < R) { const w = (1 - d / R) ** 2; if (w > cornerW[i]) { cornerW[i] = w; cornerX[i] = sign * w; } }
    }
  }

  // Eyelids: upper lid closes onto the lower lid, nearby skin follows.
  const lidDy = new Float32Array(N_LM);
  for (const eye of EYES) {
    const R = 0.075 * faceW;
    const lidMove = eye.up.map((id, k) => (k === 0 || k === 8 ? 0 : ry[eye.lo[k]] - ry[id] - 0.4));
    eye.up.forEach((id, k) => { lidDy[id] = lidMove[k]; });
    eye.lo.forEach((id, k) => { if (k > 0 && k < 8) lidDy[id] = -0.12 * lidMove[k]; });
    const own = new Set([...eye.up, ...eye.lo]);
    for (let i = 0; i < N_FACE; i++) {
      if (own.has(i)) continue;
      let best = 0;
      eye.up.forEach((id, k) => {
        if (ry[i] >= ry[id]) return;
        const d = Math.hypot(rx[i] - rx[id], ry[i] - ry[id]);
        if (d < R) best = Math.max(best, 0.6 * (1 - d / R) * lidMove[k]);
      });
      if (best > lidDy[i]) lidDy[i] = best;
    }
  }

  const brow = new Float32Array(N_LM);
  const eyeLine = (ry[159] + ry[386]) / 2;
  for (let i = 0; i < N_FACE; i++) {
    if (ry[i] > eyeLine - 0.01 * faceW) continue;
    let w = 0;
    for (const b of BROWS) {
      const d = Math.hypot(rx[i] - rx[b], ry[i] - ry[b]);
      w = Math.max(w, 1 - d / (0.2 * faceW));
    }
    brow[i] = w > 0 ? w * w : 0;
  }

  // Render vertices: one per control point, plus a duplicate strip for the
  // inside of the mouth, which is shaded instead of textured.
  const nVert = nCtl + 22;
  const uv = new Float32Array(nVert * 2), mouth = new Float32Array(nVert * 3);
  for (let i = 0; i < nCtl; i++) { uv[i * 2] = rx[i] / mesh.w; uv[i * 2 + 1] = ry[i] / mesh.h; }
  const mouthSrc = [];
  for (let k = 0; k < 11; k++) {
    for (const [row, id] of [[0, LIP_UP[k]], [1, LIP_LO[k]]]) {
      const v = nCtl + k * 2 + row;
      uv[v * 2] = rx[id] / mesh.w; uv[v * 2 + 1] = ry[id] / mesh.h;
      mouth[v * 3] = k / 10; mouth[v * 3 + 1] = row; mouth[v * 3 + 2] = 1;
      mouthSrc.push(id);
    }
  }
  const idx = [...mesh.outer, ...FACE_TRIS];
  for (const eye of EYES) {
    for (let k = 0; k < 8; k++) {
      idx.push(eye.up[k], eye.lo[k], eye.up[k + 1], eye.up[k + 1], eye.lo[k], eye.lo[k + 1]);
    }
  }
  for (let k = 0; k < 10; k++) {
    const a = nCtl + k * 2, b = a + 1, c = a + 2, d = a + 3;
    idx.push(a, b, c, c, b, d);
  }

  return {
    w: mesh.w, h: mesh.h, nCtl, nVert, rx, ry, depth, follow, faceW, cx, cy, mouthW,
    jaw, lipUp, cornerX, cornerW, lidDy, brow, uv, mouth, mouthSrc, index: new Uint16Array(idx),
    pos: new Float32Array(nVert * 2),
  };
}

function deform(m, p) {
  const { rx, ry, pos, faceW, mouthW } = m;
  const openPx = p.open * 0.3 * mouthW;
  const cosR = Math.cos(p.roll), sinR = Math.sin(p.roll);
  for (let i = 0; i < m.nCtl; i++) {
    let x = rx[i], y = ry[i];
    if (i < N_FACE) {
      y += m.jaw[i] * openPx - m.lipUp[i] * openPx * 0.16;
      x += m.cornerX[i] * mouthW * (0.1 * p.wide + 0.07 * p.smile - 0.05 * p.open);
      y -= m.cornerW[i] * mouthW * 0.085 * p.smile;
      y += m.lidDy[i] * p.blink;
      y -= m.brow[i] * faceW * 0.035 * p.brow;
    }
    const dx = x - m.cx, dy = y - m.cy, par = (m.depth[i] - 0.35) * faceW * 0.1;
    const hx = m.cx + dx * cosR - dy * sinR + p.yaw * (par + 0.02 * faceW);
    const hy = m.cy + dx * sinR + dy * cosR + p.pitch * (par + 0.015 * faceW);
    const f = m.follow[i];
    pos[i * 2] = rx[i] + f * (hx - rx[i]);
    pos[i * 2 + 1] = ry[i] + f * (hy - ry[i]);
  }
  for (let k = 0; k < 22; k++) {
    const s = m.mouthSrc[k], v = m.nCtl + k;
    pos[v * 2] = pos[s * 2]; pos[v * 2 + 1] = pos[s * 2 + 1];
  }
}

// ------------------------------------------------------------------ renderer
function createRenderer(canvas) {
  const gl = canvas.getContext("webgl", { antialias: true, alpha: false, premultipliedAlpha: false });
  if (!gl) return null;
  const compile = (type, src) => {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(prog); gl.useProgram(prog);
  const loc = {
    pos: gl.getAttribLocation(prog, "aPos"), uv: gl.getAttribLocation(prog, "aUv"),
    mouth: gl.getAttribLocation(prog, "aMouth"),
    size: gl.getUniformLocation(prog, "uSize"), open: gl.getUniformLocation(prog, "uOpen"),
  };
  const posBuf = gl.createBuffer(), uvBuf = gl.createBuffer(), mouthBuf = gl.createBuffer(), idxBuf = gl.createBuffer();
  const tex = gl.createTexture();
  let model = null;
  return {
    setModel(m, image) {
      model = m;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.bindBuffer(gl.ARRAY_BUFFER, uvBuf); gl.bufferData(gl.ARRAY_BUFFER, m.uv, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc.uv); gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, mouthBuf); gl.bufferData(gl.ARRAY_BUFFER, m.mouth, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc.mouth); gl.vertexAttribPointer(loc.mouth, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.index, gl.STATIC_DRAW);
      gl.uniform2f(loc.size, m.w, m.h);
    },
    draw(open) {
      if (!model) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.bindBuffer(gl.ARRAY_BUFFER, posBuf); gl.bufferData(gl.ARRAY_BUFFER, model.pos, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(loc.pos); gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, 0, 0);
      gl.uniform1f(loc.open, open);
      gl.drawElements(gl.TRIANGLES, model.index.length, gl.UNSIGNED_SHORT, 0);
    },
  };
}

// --------------------------------------------------------------------- voice
function createVoice(onState) {
  const el = new Audio();
  el.preload = "auto";
  let ctx = null, analyser = null, time = null, freq = null, url = null, synth = false, muted = false;
  const wire = () => {
    if (ctx) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
      analyser = ctx.createAnalyser(); analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.35;
      ctx.createMediaElementSource(el).connect(analyser); analyser.connect(ctx.destination);
      time = new Uint8Array(analyser.fftSize); freq = new Uint8Array(analyser.frequencyBinCount);
    } catch (e) { ctx = null; analyser = null; }
  };
  el.addEventListener("playing", () => onState("speaking"));
  el.addEventListener("ended", () => onState("done"));
  el.addEventListener("pause", () => { if (!el.ended) onState("done"); });
  el.addEventListener("error", () => onState("done"));

  const start = async () => {
    wire();
    try {
      if (ctx && ctx.state === "suspended") await ctx.resume();
      await el.play();
      return true;
    } catch (e) { onState("blocked"); return false; }
  };
  const stop = () => {
    try { el.pause(); } catch (e) { /* nothing was playing */ }
    if (synth) { try { window.speechSynthesis.cancel(); } catch (e) { /* unsupported */ } synth = false; }
  };
  return {
    playBase64(b64, mime) {
      stop();
      const bin = atob(b64), bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(new Blob([bytes], { type: mime || "audio/mpeg" }));
      el.src = url; el.muted = muted;
      return start();
    },
    speakText(text) {  // last resort when the server could not produce audio
      stop();
      const ss = window.speechSynthesis;
      if (!ss || muted) return false;
      const voice = ss.getVoices().find((v) => /^he|^iw/i.test(v.lang));
      if (!voice) return false;
      const u = new SpeechSynthesisUtterance(text);
      u.voice = voice; u.lang = voice.lang;
      u.onstart = () => { synth = true; onState("speaking"); };
      u.onend = u.onerror = () => { synth = false; onState("done"); };
      ss.speak(u);
      return true;
    },
    replay() { if (el.src) { el.currentTime = 0; return start(); } return false; },
    resume: start,
    stop,
    setMuted(v) { muted = v; el.muted = v; if (v && synth) stop(); },
    // loudness 0..1 and brightness 0..1 of what is being said right now
    sample(t) {
      if (synth || !analyser || (ctx && ctx.state !== "running")) {
        const a = 0.42 + 0.3 * Math.sin(t * 12.3) + 0.22 * Math.sin(t * 19.1 + 1.3) + 0.12 * Math.sin(t * 5.2);
        return { level: clamp(a, 0, 1), bright: 0.5 + 0.4 * Math.sin(t * 3.1) };
      }
      analyser.getByteTimeDomainData(time);
      let sum = 0;
      for (let i = 0; i < time.length; i++) { const v = (time[i] - 128) / 128; sum += v * v; }
      const level = clamp((Math.sqrt(sum / time.length) - 0.012) / 0.17, 0, 1) ** 0.7;
      analyser.getByteFrequencyData(freq);
      const hz = ctx.sampleRate / analyser.fftSize;
      let lo = 0, hi = 0;
      for (let i = 2; i < freq.length; i++) {
        const f = i * hz;
        if (f < 1200) lo += freq[i]; else if (f < 7000) hi += freq[i];
      }
      return { level, bright: hi / (lo + hi + 1) };
    },
    destroy() { stop(); if (url) URL.revokeObjectURL(url); if (ctx) ctx.close().catch(() => {}); },
  };
}

// ------------------------------------------------------------------ instance
const STATE_LABEL = { speaking: "מדבר", listening: "מקשיב", thinking: "חושב", idle: "" };

function createAvatar(root) {
  const $ = (id) => root.querySelector("#" + id);
  const tile = $("tile"), canvas = $("gl"), stateEl = $("state"), clockEl = $("clock");
  const tapBtn = $("tap"), muteBtn = $("mute"), replayBtn = $("replay"), fallbackImg = $("still");
  const renderer = createRenderer(canvas);
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let data = {}, model = null, personaKey = null, turn = null, state = "idle", busy = false, busySince = 0;
  let raf = 0, alive = true, last = performance.now() / 1000;
  const cur = { open: 0, wide: 0, smile: 0, blink: 0, brow: 0, yaw: 0, pitch: 0, roll: 0 };
  let spokeAt = 0;
  let level = 0, emphasis = 0, nextBlink = last + rand(1.5, 4), blinkT = -1, nextNod = last + rand(3, 6), nodT = -1;
  const seed = Math.random() * 100;

  const setState = (s) => {
    state = s;
    tile.dataset.state = s;
    stateEl.textContent = STATE_LABEL[s] || "";
  };
  const voice = createVoice((ev) => {
    if (ev === "speaking") { tapBtn.hidden = true; spokeAt = performance.now() / 1000; setState("speaking"); }
    else if (ev === "blocked") { tapBtn.hidden = false; setState("listening"); }
    else if (state === "speaking") { setState(data.live ? "listening" : "idle"); blinkT = 0; }
  });

  tapBtn.addEventListener("click", () => { tapBtn.hidden = true; voice.resume(); });
  replayBtn.addEventListener("click", () => voice.replay());
  muteBtn.addEventListener("click", () => {
    const m = muteBtn.getAttribute("aria-pressed") !== "true";
    muteBtn.setAttribute("aria-pressed", String(m));
    muteBtn.title = m ? "הפעל קול" : "השתק";
    voice.setMuted(m);
  });

  // The avatar "thinks" while the app is working on the next reply.
  const app = document.querySelector('[data-testid="stApp"]');
  const readBusy = () => {
    const now = !!app && app.getAttribute("data-test-script-state") === "running";
    if (now && !busy) busySince = performance.now() / 1000;
    busy = now;
  };
  const observer = app ? new MutationObserver(readBusy) : null;
  if (observer) observer.observe(app, { attributes: true, attributeFilter: ["data-test-script-state"] });

  const loadPersona = (d) => {
    personaKey = d.persona;
    tile.style.setProperty("--accent", d.accent || "#2f5bea");
    $("pname").textContent = d.name || "";
    $("ptitle").textContent = d.title || "";
    const img = new Image();
    img.onload = () => {
      if (!alive || personaKey !== d.persona) return;
      if (renderer) { model = buildModel(d.mesh); renderer.setModel(model, img); tile.classList.add("ready"); }
    };
    img.src = "data:image/jpeg;base64," + d.photo;
    fallbackImg.src = img.src;
  };

  const fmtClock = () => {
    if (!data.started) { clockEl.textContent = ""; return; }
    const end = data.ended || Date.now() / 1000;
    const s = Math.max(0, Math.floor(end - data.started));
    clockEl.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  };

  const frame = () => {
    if (!alive) return;
    raf = requestAnimationFrame(frame);
    const t = performance.now() / 1000, dt = Math.min(0.05, t - last); last = t;
    const mood = data.mood || {};
    const energy = (mood.energy ?? 1) * (reduceMotion ? 0.25 : 1);
    // the candidate answered while the interviewer was still talking: stop and listen
    if (busy && state === "speaking" && busySince > spokeAt + 0.2 && t - busySince > 0.3) voice.stop();
    const thinking = busy && t - busySince > 0.45 && state !== "speaking";
    const shown = thinking ? "thinking" : state;
    if (tile.dataset.state !== shown) { tile.dataset.state = shown; stateEl.textContent = STATE_LABEL[shown] || ""; }

    const tgt = { open: 0, wide: 0, smile: mood.smile ?? 0, brow: mood.brow ?? 0, yaw: 0, pitch: 0, roll: 0 };
    // slow drift that never quite repeats
    tgt.yaw += energy * (0.22 * Math.sin(t * 0.31 + seed) + 0.1 * Math.sin(t * 0.83 + seed * 2));
    tgt.pitch += energy * (0.12 * Math.sin(t * 0.47 + seed * 3) + 0.06 * Math.sin(t * 1.1 + seed));
    tgt.roll += energy * 0.012 * Math.sin(t * 0.27 + seed * 5);

    if (state === "speaking") {
      const s = voice.sample(t);
      level += (s.level - level) * (s.level > level ? 0.6 : 0.3);
      emphasis += (level - emphasis) * 0.06;
      const sibilant = smooth(0.5, 0.75, s.bright);
      tgt.open = level * (1 - 0.55 * sibilant) * (mood.mouth ?? 1);
      tgt.wide = (s.bright - 0.42) * 1.5;
      tgt.pitch += energy * (0.5 * (level - emphasis) + 0.12 * emphasis);
      tgt.brow += 0.9 * Math.max(0, level - emphasis - 0.12);
      tgt.yaw += energy * 0.1 * Math.sin(t * 1.7 + seed);
    } else {
      level *= 0.6; emphasis *= 0.9;
    }
    if (thinking) { tgt.yaw += 0.5; tgt.pitch -= 0.42; tgt.brow += 0.35; tgt.roll += 0.02; }
    if (shown === "listening") {
      tgt.roll += 0.018 * (mood.tilt ?? 1);
      if (nodT < 0 && t > nextNod) { nodT = 0; nextNod = t + rand(4, 9) / Math.max(0.3, mood.nods ?? 1); }
    }
    if (nodT >= 0) {
      nodT += dt / 0.7;
      if (nodT >= 1) nodT = -1; else tgt.pitch += 0.75 * energy * Math.sin(Math.PI * nodT) ** 2;
    }
    if (blinkT < 0 && t > nextBlink) blinkT = 0;
    let blink = 0;
    if (blinkT >= 0) {
      blinkT += dt / 0.19;
      if (blinkT >= 1) { blinkT = -1; nextBlink = t + (Math.random() < 0.15 ? 0.25 : rand(2.2, 5.5) / (mood.blinks ?? 1)); }
      else blink = Math.sin(Math.PI * blinkT) ** 0.7;
    }
    if (data.pose) Object.assign(tgt, data.pose);  // test hook: freeze an exact pose

    const ease = (k, rate) => { cur[k] += (tgt[k] - cur[k]) * (data.pose ? 1 : 1 - Math.exp(-dt * rate)); };
    ease("open", 26); ease("wide", 14); ease("smile", 3); ease("brow", 7);
    ease("yaw", 2.6); ease("pitch", 3.2); ease("roll", 2.2);
    cur.blink = data.pose && data.pose.blink != null ? data.pose.blink : blink;

    if (model && renderer) { deform(model, cur); renderer.draw(cur.open); }
    if (!reduceMotion) {
      const b = Math.sin(t * 1.25 + seed);
      canvas.style.transform = `scale(1.03) translateY(${(0.28 * b).toFixed(3)}%)`;
    }
    if ((t | 0) !== ((t - dt) | 0)) fmtClock();
  };

  setState("idle");
  readBusy();
  raf = requestAnimationFrame(frame);

  return {
    update(d) {
      data = d || {};
      if (data.persona && data.persona !== personaKey) loadPersona(data);
      fmtClock();
      if (!data.live) { if (state !== "speaking") setState("idle"); }
      else if (state === "idle") setState("listening");
      if (data.turn != null && data.turn !== turn) {
        turn = data.turn;
        if (data.audio) voice.playBase64(data.audio, data.mime);
        else if (data.text && !voice.speakText(data.text)) setState(data.live ? "listening" : "idle");
      }
      replayBtn.hidden = !data.audio;
    },
    destroy() {
      alive = false; cancelAnimationFrame(raf);
      if (observer) observer.disconnect();
      voice.destroy();
    },
  };
}

export default function (component) {
  const { data, parentElement } = component;
  let inst = parentElement.__imAvatar;
  if (!inst) { inst = createAvatar(parentElement); parentElement.__imAvatar = inst; }
  inst.update(data);
  return () => { inst.destroy(); parentElement.__imAvatar = null; };
}

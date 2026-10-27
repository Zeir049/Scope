// ============================================================
// 임베딩 로딩 화면
// ------------------------------------------------------------
// 조준선(스코프) + 떠다니는 원/타원 + 아래쪽 ASCII 지형으로 이루어진 로딩 오버레이입니다.
//
//  - 다크 모드: 조준선/원/글자 = 흰색 / 라이트 모드: 검은색  (테마 전환 시 즉시 반영)
//  - ASCII 지형, 하단 빛, 확산 링 = 사용자가 테마에서 고른 강조색(--teal)
//  - 배경은 반투명 + 살짝 블러라서 뒤의 화면이 은은하게 비쳐 보입니다.
//
// 사용법 (script.js):
//   import { showEmbeddingLoader, updateEmbeddingLoader, hideEmbeddingLoader } from "./embedding-loader.js";
//
//   showEmbeddingLoader({ title: "임베딩 중", sub: "이전 회차와의 연관도를 계산하고 있어요" });
//   updateEmbeddingLoader({ sub: "사건 3 / 12 임베딩 중" });   // (선택) 진행 상황 갱신
//   await hideEmbeddingLoader();
// ============================================================

const MIN_VISIBLE_MS = 600; // 너무 빨리 끝나도 깜빡이듯 사라지지 않도록 최소 노출 시간
const FADE_MS = 260;
const FRAME_MS = 1000 / 30; // 30fps면 충분해서 자원을 아낍니다.

const RAMP = [".", ":", "/", "\\", "=", "+", "#", "%", "@"];

let root = null;
let canvas = null;
let ctx = null;
let titleEl = null;
let subEl = null;

let shownAt = 0;
let refCount = 0;
let rafId = 0;
let hideTimer = 0;
let lastFrame = 0;
let startTime = 0;

let width = 0;
let height = 0;
let dpr = 1;

let accentRGB = "34,197,94";
let colorCheck = 0;

const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;

// ---------- DOM ----------
function ensureDom() {
  if (root) return;

  root = document.createElement("div");
  root.className = "embedding-loader";
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "polite");
  root.setAttribute("aria-hidden", "true");
  root.innerHTML = `
    <canvas class="embedding-loader-canvas"></canvas>
    <div class="embedding-loader-text">
      <div class="embedding-loader-title"><span class="el-title-text"></span><span class="el-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span></div>
      <div class="embedding-loader-sub"></div>
    </div>
  `;
  document.body.appendChild(root);

  canvas = root.querySelector("canvas");
  ctx = canvas.getContext("2d");
  titleEl = root.querySelector(".el-title-text");
  subEl = root.querySelector(".embedding-loader-sub");

  window.addEventListener("resize", () => {
    if (root.classList.contains("visible")) resize();
  });
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  width = Math.round(rect.width);
  height = Math.round(rect.height);
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  layoutText();
}

// 크기 단위: 화면이 작든 크든 그림 전체의 비율이 유지되도록 하는 기준값
function unit() {
  return Math.max(0.65, Math.min(1.5, Math.min(width, height) / 566));
}
function reticleCenter() {
  return { x: width / 2, y: height * 0.44 };
}
function layoutText() {
  const u = unit();
  const c = reticleCenter();
  const textEl = root.querySelector(".embedding-loader-text");
  textEl.style.top = `${Math.round(c.y + 84 * u * 1.55)}px`;
}

// ---------- 색상 ----------
function isDarkTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

// 사용자가 고른 강조색(--teal)을 "r,g,b" 로 읽습니다. 라이트 모드에서는 흰 배경에서도 보이도록 진한 쪽(--teal-dark)을 씁니다.
function readAccentRGB() {
  const cs = getComputedStyle(document.documentElement);
  let hex = cs.getPropertyValue(isDarkTheme() ? "--teal" : "--teal-dark").trim() || cs.getPropertyValue("--teal").trim();
  hex = hex.replace("#", "");
  if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
  const num = parseInt(hex, 16);
  if (hex.length !== 6 || Number.isNaN(num)) return "34,197,94";
  return `${(num >> 16) & 255},${(num >> 8) & 255},${num & 255}`;
}

// ---------- 그리기 요소 ----------
// 떠다니는 원/타원. fx, fy는 화면 대비 위치 비율, rx/ry는 크기(단위 u 배), ax/ay는 떠다니는 폭
const FLOATERS = [
  { fx: 0.5, fy: 0.045, rx: 41, ry: 29, rot: 0, ax: 26, ay: 10, sp: 0.35, ph: 0.0, spin: 0.05 },
  { fx: 0.645, fy: 0.24, rx: 18, ry: 18, rot: 0, ax: 14, ay: 18, sp: 0.5, ph: 1.6, spin: 0 },
  { fx: 0.37, fy: 0.67, rx: 17, ry: 17, rot: 0, ax: 18, ay: 12, sp: 0.42, ph: 3.1, spin: 0 },
  { fx: 0.166, fy: 0.8, rx: 54, ry: 30, rot: -0.36, ax: 22, ay: 12, sp: 0.3, ph: 4.4, spin: -0.04 },
  { fx: 0.83, fy: 0.58, rx: 30, ry: 14, rot: 0.3, ax: 20, ay: 14, sp: 0.38, ph: 2.2, spin: 0.06 },
  { fx: 0.24, fy: 0.22, rx: 12, ry: 12, rot: 0, ax: 12, ay: 16, sp: 0.55, ph: 5.3, spin: 0 },
];

function strokeEllipse(x, y, rx, ry, rot, alpha, ink, lw) {
  ctx.beginPath();
  ctx.ellipse(x, y, Math.max(1, rx), Math.max(1, ry), rot, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${ink},${alpha})`;
  ctx.lineWidth = lw;
  ctx.stroke();
}

function drawFloaters(t, ink, u) {
  for (const f of FLOATERS) {
    const x = f.fx * width + Math.sin(t * f.sp + f.ph) * f.ax * u;
    const y = f.fy * height + Math.cos(t * f.sp * 0.8 + f.ph) * f.ay * u;
    const alpha = 0.55 + 0.4 * Math.sin(t * 0.9 + f.ph);
    strokeEllipse(x, y, f.rx * u, f.ry * u, f.rot + t * f.spin, alpha, ink, 1.2);
  }
}

function drawReticle(t, ink, u) {
  const c = reticleCenter();
  const pulse = Math.sin(t * 2.2) * 4 * u;
  const rot = reduceMotion ? 0 : t * 0.22;
  const inner = 50 * u + pulse * 0.5;
  const outer = 88 * u + pulse;

  ctx.strokeStyle = `rgba(${ink},1)`;
  ctx.lineWidth = 2 * Math.max(0.85, u);
  ctx.lineCap = "butt";
  ctx.beginPath();
  for (let k = 0; k < 8; k++) {
    const a = rot + (k * Math.PI) / 4 - Math.PI / 2;
    ctx.moveTo(c.x + Math.cos(a) * inner, c.y + Math.sin(a) * inner);
    ctx.lineTo(c.x + Math.cos(a) * outer, c.y + Math.sin(a) * outer);
  }
  ctx.stroke();

  // 조준선 아래에 걸리는 타원 (이미지의 락온 표시)
  const breathe = 1 + Math.sin(t * 1.6) * 0.06;
  strokeEllipse(c.x, c.y + 88 * u, 52 * u * breathe, 19 * u * breathe, 0, 1, ink, 1.3);
}

// 조준선 중심에서 퍼져 나가는 강조색 링 (로딩 중이라는 신호)
function drawPulseRings(t, u) {
  const c = reticleCenter();
  for (let i = 0; i < 2; i++) {
    const p = ((t * 0.32 + i * 0.5) % 1 + 1) % 1;
    const r = (100 + p * 170) * u;
    const alpha = (1 - p) * 0.28;
    ctx.beginPath();
    ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(${accentRGB},${alpha})`;
    ctx.lineWidth = 1.2;
    ctx.stroke();
  }
}

function heightAt(x, t) {
  const a = Math.sin(x * 0.045 + t * 0.35) * 0.5;
  const b = Math.sin(x * 0.11 - t * 0.22 + 1.7) * 0.3;
  const c = Math.sin(x * 0.29 + t * 0.6 + 4.1) * 0.2;
  const v = Math.max(0, Math.min(1, 0.5 + (a + b + c) * 0.55));
  return Math.pow(v, 1.5);
}

function hash(a, b) {
  let h = (Math.imul(a, 73856093) ^ Math.imul(b, 19349663)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return (h % 1000) / 1000;
}

// 하단 ASCII 지형 (강조색). 위쪽은 옅고 아래로 갈수록 진하고 촘촘합니다.
function drawTerrain(t) {
  const cellW = 8;
  const cellH = 11;
  const cols = Math.ceil(width / cellW) + 1;
  const maxRows = Math.max(6, Math.floor((height * 0.3) / cellH));
  const bottomY = height - 4;
  const scroll = reduceMotion ? 0 : t * 1.6;
  const shimmer = Math.floor(t * 2);

  ctx.font = `${cellH}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  ctx.textBaseline = "bottom";
  ctx.textAlign = "left";
  ctx.fillStyle = `rgb(${accentRGB})`;

  let prev = heightAt(scroll - 1, t);
  for (let col = 0; col < cols; col++) {
    const hf = heightAt(col + scroll, t);
    const next = heightAt(col + 1 + scroll, t);
    const rows = Math.round(2 + hf * (maxRows - 2));
    const x = col * cellW;

    for (let r = 0; r < rows; r++) {
      const depth = rows <= 1 ? 1 : r / (rows - 1); // 0 = 지형 꼭대기, 1 = 바닥
      const y = bottomY - (rows - 1 - r) * cellH;
      const seed = hash(col, r);
      let ch;
      if (r === 0) {
        ch = next > prev + 0.004 ? "/" : next < prev - 0.004 ? "\\" : seed > 0.5 ? "^" : "-";
      } else {
        const idx = Math.min(RAMP.length - 1, Math.floor(depth * RAMP.length * 0.9 + seed * 2.2));
        ch = RAMP[idx];
        if (seed < 0.05) ch = RAMP[(idx + shimmer) % RAMP.length]; // 일부 글자만 반짝
      }
      ctx.globalAlpha = 0.16 + depth * 0.62;
      ctx.fillText(ch, x, y);
    }
    prev = hf;
  }
  ctx.globalAlpha = 1;
}

function drawGlow(u) {
  // 아래쪽에서 은은하게 올라오는 강조색 빛
  const g = ctx.createLinearGradient(0, height, 0, height * 0.55);
  g.addColorStop(0, `rgba(${accentRGB},0.16)`);
  g.addColorStop(1, `rgba(${accentRGB},0)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, height * 0.55, width, height * 0.45);

  // 조준선 주변의 아주 옅은 빛
  const c = reticleCenter();
  const r = 260 * u;
  const rg = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, r);
  rg.addColorStop(0, `rgba(${accentRGB},0.09)`);
  rg.addColorStop(1, `rgba(${accentRGB},0)`);
  ctx.fillStyle = rg;
  ctx.fillRect(c.x - r, c.y - r, r * 2, r * 2);
}

function frame(now) {
  rafId = requestAnimationFrame(frame);
  if (now - lastFrame < FRAME_MS) return;
  lastFrame = now;
  if (!startTime) startTime = now;
  if (width === 0) return;

  // 테마/강조색이 바뀌어도 반영되도록 가끔 다시 읽습니다.
  if (colorCheck++ % 20 === 0) accentRGB = readAccentRGB();

  const t = reduceMotion ? 0 : (now - startTime) / 1000;
  const ink = isDarkTheme() ? "255,255,255" : "0,0,0"; // 가시성을 위해 순백/순흑
  const u = unit();

  ctx.clearRect(0, 0, width, height);
  drawGlow(u);
  drawTerrain(t);
  drawPulseRings(t, u);
  drawFloaters(t, ink, u);
  drawReticle(t, ink, u);
}

// ---------- 공개 API ----------
export function showEmbeddingLoader({ title = "임베딩 중", sub = "" } = {}) {
  ensureDom();
  refCount++;
  clearTimeout(hideTimer);

  titleEl.textContent = title;
  subEl.textContent = sub;

  if (!root.classList.contains("visible")) {
    shownAt = performance.now();
    root.classList.add("visible");
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("embedding-loading");
    accentRGB = readAccentRGB();
    startTime = 0;
    resize();
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(frame);
  }
}

export function updateEmbeddingLoader({ title, sub } = {}) {
  if (!root) return;
  if (title !== undefined) titleEl.textContent = title;
  if (sub !== undefined) subEl.textContent = sub;
}

export function hideEmbeddingLoader() {
  if (!root || refCount === 0) return Promise.resolve();
  refCount = Math.max(0, refCount - 1);
  if (refCount > 0) return Promise.resolve();

  const wait = Math.max(0, MIN_VISIBLE_MS - (performance.now() - shownAt));
  return new Promise((resolve) => {
    hideTimer = setTimeout(() => {
      root.classList.remove("visible");
      root.setAttribute("aria-hidden", "true");
      document.body.classList.remove("embedding-loading");
      setTimeout(() => {
        // 페이드아웃이 끝난 뒤에만 그리기를 멈춥니다.
        if (!root.classList.contains("visible")) cancelAnimationFrame(rafId);
        resolve();
      }, FADE_MS);
    }, wait);
  });
}

// 편의 함수: 작업 전후로 자동으로 켜고 끕니다.
export async function withEmbeddingLoader(task, options) {
  showEmbeddingLoader(options);
  try {
    return await task();
  } finally {
    await hideEmbeddingLoader();
  }
}

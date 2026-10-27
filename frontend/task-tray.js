// ============================================================
// 우측 하단 작업 창 (분석 진행 상황) — 서버 상태를 폴링해 그린다 (D16)
// ------------------------------------------------------------
// 진행 상태의 진실은 서버의 chapters.status 하나다. 이 창은 그걸 보여주기만 한다.
//   - 진행 중 작업 목록: GET /jobs/active (1.5초마다, 진행 중 작업이 없으면 폴링 중단)
//   - 목록에서 빠진 작업은 GET /chapters/{no}/result 로 최종 상태를 확인해 완료/실패 처리
//   - 새로고침·다른 기기에서도 restoreActiveJobs() 한 번이면 진행 중 작업이 다시 보인다
//
// 사용법 (script.js):
//   trackJob({ projectId, projectName, chapterNo, title, status: "extracting" });
//   onJobFinished((job, result) => { ...화면 갱신... });
//   setJobActionHandler((job, result) => { ...결과 화면 열기... });
//   showNotice({ title, message, detail, kind: "failed" | "info" | "done", actionLabel, onAction });
// ============================================================
import { api } from "./api.js";
import { JOB_POLL_INTERVAL_MS } from "./config.js";

const MAX_FINISHED_CARDS = 3; // 끝난 카드(완료·실패·안내)는 최근 몇 개만 남긴다
const SAVE_WAIT_POLLS = 4; // 검수 뒤 reviewed → saved(auto_save)를 기다리는 폴링 횟수

let trayEl = null;
let bodyEl = null;
let headCountEl = null;
let collapsed = false;
let tickTimer = 0;
let pollTimer = 0;
let polling = false;

const cards = []; // 최신이 앞. { el, running, ... }
const jobs = new Map(); // `${projectId}:${chapterNo}` → job
const finishListeners = new Set();
let actionHandler = null;

const jobKey = (projectId, chapterNo) => `${projectId}:${chapterNo}`;
const isBusy = (status) => status === "extracting" || status === "reviewing";

// ---------- DOM ----------
function ensureTray() {
  if (trayEl) return;

  trayEl = document.createElement("section");
  trayEl.className = "task-tray hidden";
  trayEl.setAttribute("aria-label", "분석 작업");
  trayEl.innerHTML = `
    <header class="task-tray-head">
      <span class="task-tray-title">분석 작업</span>
      <span class="task-tray-count"></span>
      <button type="button" class="task-tray-toggle" aria-label="작업 창 접기">–</button>
    </header>
    <div class="task-tray-body" aria-live="polite"></div>
  `;
  document.body.appendChild(trayEl);

  bodyEl = trayEl.querySelector(".task-tray-body");
  headCountEl = trayEl.querySelector(".task-tray-count");
  const toggle = trayEl.querySelector(".task-tray-toggle");
  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    trayEl.classList.toggle("collapsed", collapsed);
    toggle.textContent = collapsed ? "+" : "–";
    toggle.setAttribute("aria-label", collapsed ? "작업 창 펼치기" : "작업 창 접기");
  });
}

function expandTray() {
  if (collapsed) trayEl.querySelector(".task-tray-toggle").click();
}

function formatElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderHeadCount() {
  const running = cards.filter((c) => c.running).length;
  headCountEl.textContent = running ? `${running}건 진행 중` : "";
  trayEl.classList.toggle("hidden", cards.length === 0);
}

// 진행 중 작업의 경과 시간을 1초마다 갱신한다 (진행 중 카드가 있을 때만 타이머가 돈다).
function syncTicker() {
  const anyRunning = cards.some((c) => c.running);
  if (anyRunning && !tickTimer) {
    tickTimer = setInterval(() => {
      for (const c of cards) if (c.running) c.renderTime?.();
    }, 1000);
  } else if (!anyRunning && tickTimer) {
    clearInterval(tickTimer);
    tickTimer = 0;
  }
}

function addCard(card) {
  ensureTray();
  cards.unshift(card);
  bodyEl.prepend(card.el);
  expandTray(); // 새 카드가 생기면 접혀 있던 창도 펼친다
  renderHeadCount();
  syncTicker();
}

function removeCard(card) {
  const idx = cards.indexOf(card);
  if (idx !== -1) cards.splice(idx, 1);
  card.el.remove();
  if (card.job) jobs.delete(card.job.key);
  renderHeadCount();
  syncTicker();
}

function pruneFinished() {
  const finished = cards.filter((c) => !c.running);
  for (const c of finished.slice(MAX_FINISHED_CARDS)) removeCard(c);
}

function cardSkeleton(title) {
  const el = document.createElement("article");
  el.className = "task-card";
  el.dataset.status = "running";
  el.innerHTML = `
    <div class="task-card-head">
      <span class="task-card-title"></span>
      <button type="button" class="task-card-close" aria-label="닫기">×</button>
    </div>
    <ol class="task-stages"></ol>
    <p class="task-message hidden"></p>
    <p class="task-detail hidden"></p>
    <div class="task-actions hidden"><button type="button" class="task-action"></button></div>
  `;
  el.querySelector(".task-card-title").textContent = title;
  return el;
}

function setCardMessage(el, message, detail) {
  const messageEl = el.querySelector(".task-message");
  messageEl.textContent = message;
  messageEl.classList.toggle("hidden", !message);
  const detailEl = el.querySelector(".task-detail");
  const showDetail = !!detail && detail !== message;
  detailEl.textContent = showDetail ? detail : "";
  detailEl.classList.toggle("hidden", !showDetail);
}

function setCardAction(card, label, onAction) {
  const actionsEl = card.el.querySelector(".task-actions");
  const btn = card.el.querySelector(".task-action");
  if (!label || !onAction) {
    actionsEl.classList.add("hidden");
    return;
  }
  btn.textContent = label;
  btn.onclick = () => {
    removeCard(card);
    onAction();
  };
  actionsEl.classList.remove("hidden");
}

// ---------- 작업(회차 1개의 추출/검수) 카드 ----------
const PHASE_LABELS = {
  extracting: "1차 추출 중",
  reviewing: "2차 검수 중",
  saving: "저장 중",
};
const DONE_LABELS = { extract: "1차 추출", review: "2차 검수" };

function createJobCard(job) {
  const el = cardSkeleton(`${job.projectName || "프로젝트"} · ${job.chapterNo}화`);
  const li = document.createElement("li");
  li.className = "task-stage";
  li.dataset.state = "active";
  li.innerHTML = `
    <span class="task-stage-icon" aria-hidden="true"></span>
    <span class="task-stage-label"></span>
    <span class="task-stage-detail"></span>
    <span class="task-stage-time"></span>
  `;
  el.querySelector(".task-stages").appendChild(li);

  const card = {
    el,
    job,
    running: true,
    renderTime() {
      const end = job.endedAt || Date.now();
      li.querySelector(".task-stage-time").textContent = formatElapsed(end - job.startedAt);
    },
    render() {
      li.querySelector(".task-stage-label").textContent = card.running
        ? PHASE_LABELS[job.phase] || "진행 중"
        : DONE_LABELS[job.kind];
      let detail = "";
      if (!card.running) detail = "";
      else if (job.stale) detail = "응답 없음(서버가 정리합니다)";
      else if (job.progress != null && job.phase !== "saving") detail = `${job.progress}%`;
      li.querySelector(".task-stage-detail").textContent = detail;
      li.classList.toggle("is-stale", !!job.stale);
      card.renderTime();
    },
    finish(state, message, detail) {
      card.running = false;
      job.endedAt = Date.now();
      li.dataset.state = state === "failed" ? "failed" : "done";
      el.dataset.status = state;
      setCardMessage(el, message, detail);
      card.render();
      renderHeadCount();
      syncTicker();
      pruneFinished();
    },
  };
  // 진행 중 카드의 닫기 버튼은 CSS 가 숨긴다(작업은 서버에서 계속 돌기 때문). 끝난 카드만 닫힌다.
  el.querySelector(".task-card-close").addEventListener("click", () => {
    if (!card.running) removeCard(card);
  });
  return card;
}

/**
 * 서버에서 진행 중인 회차 작업을 창에 올린다(이미 있으면 갱신).
 * status: extracting | reviewing. 작업을 직접 시작했을 때와 /jobs/active 복원 때 같이 쓴다.
 */
export function trackJob({ projectId, projectName, chapterNo, title, status, progress = null, startedAt = null, stale = false }) {
  const key = jobKey(projectId, chapterNo);
  let job = jobs.get(key);
  if (job && !job.card.running) {
    removeCard(job.card); // 끝난 카드에 새 작업이 오면(재검수 등) 새 카드로
    job = null;
  }
  if (!job) {
    job = {
      key,
      projectId,
      projectName,
      chapterNo,
      title,
      kind: status === "reviewing" ? "review" : "extract",
      phase: status,
      progress,
      stale,
      startedAt: startedAt ? Date.parse(startedAt) || Date.now() : Date.now(),
      endedAt: 0,
      savePolls: 0,
    };
    job.card = createJobCard(job);
    jobs.set(key, job);
    addCard(job.card);
  } else {
    if (projectName) job.projectName = projectName;
    if (status && isBusy(status)) {
      if (status === "reviewing") job.kind = "review";
      job.phase = status;
    }
    job.progress = progress;
    job.stale = stale;
  }
  job.card.render();
  startPolling();
  return job;
}

export function onJobFinished(cb) {
  finishListeners.add(cb);
  return () => finishListeners.delete(cb);
}

/** 끝난 카드의 "결과 보기" 버튼이 부를 함수 (script.js 가 결과 화면을 연다). */
export function setJobActionHandler(cb) {
  actionHandler = cb;
}

function finishJob(job, result) {
  const status = result?.status;
  const what = job.kind === "review" ? "2차 검수" : "1차 추출";
  let state = "done";
  let message = "";
  let detail = "";
  if (!result) {
    state = "failed";
    message = "회차를 찾을 수 없어요. 삭제되었을 수 있어요.";
  } else if (status === "failed") {
    state = "failed";
    message = `${result.failed_stage === "review" ? "2차 검수" : "1차 추출"} 실패`;
    detail = result.detail || "";
  } else if (status === "extracted") {
    message = "1차 추출 완료 — 결과를 확인해주세요";
  } else if (status === "saved") {
    const n = (result.contradictions || []).length;
    message = job.kind === "review" ? `검수·저장 완료 — 모순 ${n}건` : "저장 완료";
  } else if (status === "reviewed") {
    state = "failed";
    message = "검수는 끝났지만 저장되지 않았어요. 결과 화면에서 \"저장 재시도\"를 눌러주세요.";
  } else {
    message = `${what} 종료 (${status})`;
  }
  job.card.finish(state, message, detail);
  if (result && actionHandler) setCardAction(job.card, "결과 보기", () => actionHandler(job, result));
  for (const cb of finishListeners) {
    try {
      cb(job, result);
    } catch (e) {
      console.error(e);
    }
  }
}

// 활성 목록에서 빠진 작업 → 결과로 최종 상태 확인
async function resolveFinished(job) {
  let result;
  try {
    result = await api.chapters.result(job.projectId, job.chapterNo);
  } catch (e) {
    if (e.status === 404 || e.status === 403) finishJob(job, null);
    return; // 일시 오류면 다음 폴링에서 다시
  }
  if (isBusy(result.status)) {
    job.phase = result.status;
    job.card.render();
    return;
  }
  // auto_save: reviewing → reviewed → saved. reviewed 를 잠깐 보고 끝내지 않도록 몇 번 더 기다린다.
  if (result.status === "reviewed" && job.kind === "review" && job.savePolls < SAVE_WAIT_POLLS) {
    job.savePolls++;
    job.phase = "saving";
    job.card.render();
    return;
  }
  finishJob(job, result);
}

async function pollOnce() {
  let items;
  try {
    items = (await api.jobs.active()).items || [];
  } catch (e) {
    if (e.status === 401) return false; // 로그인이 끝났다 → 폴링 중단
    return true; // 일시 오류 → 다음 주기에 다시
  }

  const active = new Set();
  for (const it of items) {
    active.add(jobKey(it.project_id, it.chapter_no));
    trackJob({
      projectId: it.project_id,
      projectName: it.project_name,
      chapterNo: it.chapter_no,
      title: it.title,
      status: it.status,
      progress: it.progress,
      startedAt: it.started_at,
      stale: it.stale,
    });
  }
  const gone = [...jobs.values()].filter((j) => j.card.running && !active.has(j.key));
  await Promise.all(gone.map(resolveFinished));
  return [...jobs.values()].some((j) => j.card.running);
}

function startPolling() {
  if (polling) return;
  polling = true;
  const loop = async () => {
    const keep = await pollOnce();
    if (!polling) return;
    if (keep) pollTimer = setTimeout(loop, JOB_POLL_INTERVAL_MS);
    else polling = false; // 진행 중 작업이 없으면 폴링 중단
  };
  pollTimer = setTimeout(loop, JOB_POLL_INTERVAL_MS);
}

/** 로그인 직후: 서버에 진행 중인 작업이 있으면 창에 다시 올린다 (새로고침·다른 기기 복원). */
export async function restoreActiveJobs() {
  const keep = await pollOnce();
  if (keep) startPolling();
}

/** 로그아웃: 폴링을 멈추고 창을 비운다. */
export function resetTray() {
  polling = false;
  clearTimeout(pollTimer);
  for (const c of [...cards]) removeCard(c);
}

// ---------- 한 번 보여주는 안내 카드 (업로드 실패, 중복 원고, 서버 연결 실패 등) ----------
export function showNotice({ title, message, detail = "", kind = "failed", actionLabel, onAction }) {
  const el = cardSkeleton(title);
  el.dataset.status = kind === "failed" ? "failed" : "done";
  el.querySelector(".task-stages").remove();
  const card = { el, running: false };
  el.querySelector(".task-card-close").addEventListener("click", () => removeCard(card));
  setCardMessage(el, message, detail);
  setCardAction(card, actionLabel, onAction);
  addCard(card);
  pruneFinished();
  return card;
}

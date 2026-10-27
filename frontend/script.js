// Glitch 프론트 — 화면 그리기와 이벤트. 서버 데이터는 store.js(→ api.js)로만 읽고 쓴다.
// 진행 상태의 진실은 서버 chapters.status 하나이고, 이 파일은 그걸 보여주기만 한다.
//
// 모듈 구성:
//   store.js       데이터 접근 한 곳 — API 호출 + 열린 프로젝트의 메모리 캐시 (브라우저 저장소 안 씀)
//   api.js         계약서(docs/glitch_api_contract.md) 엔드포인트 클라이언트, 401 → 토큰 1회 재교환
//   delta-view.js  canon_delta → 1차 탭 6분류(entity_key 유지), 모순 → 2차 카드, 상태 라벨
//   canon-view.js  시각화 탭의 유일한 렌더러 — 캐논 6뷰(전체·회차별) + 저장 전 canon_delta
//   task-tray.js   우측 하단 작업 창 — GET /jobs/active 폴링
//   auth/          backend-auth.js(Firebase ID 토큰 → JWT), demo-auth.js(?demo=1 데모 로그인)
import { auth, provider, DEMO } from "./auth/demo-auth.js";
import { ensureBackendToken, onBackendAuthFailed } from "./auth/backend-auth.js";
import { store } from "./store.js";
import {
  CANON_VIEW_OF,
  bindCanonView,
  characterNames,
  deltaToCanonViews,
  hasReplacedRows,
  renderCanonView,
  sourceChapterMap,
} from "./canon-view.js";
import { chapterStatusLabel, deltaToView, isBusyStatus, toIssues, toPatchBody } from "./delta-view.js";
import {
  trackJob,
  onJobFinished,
  setJobActionHandler,
  showNotice,
  restoreActiveJobs,
  resetTray,
} from "./task-tray.js";
import { showEmbeddingLoader, hideEmbeddingLoader } from "./embedding-loader.js";
import { signInWithPopup, onAuthStateChanged, signOut } from "./auth/demo-auth.js";

// ---------- 화면 요소 ----------
const appSidebar = document.getElementById("app-sidebar");
const sidebarHamburgerBtn = document.getElementById("sidebar-hamburger-btn");
const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");
const sidebarToggleIcon = document.getElementById("sidebar-toggle-icon");
const sidebarLogoBtn = document.getElementById("sidebar-logo-btn");
const sidebarHomeBtn = document.getElementById("sidebar-home-btn");
const sidebarRecentBtn = document.getElementById("sidebar-recent-btn");
const sidebarSearchInput = document.getElementById("sidebar-search-input");
const sidebarNewProjectBtn = document.getElementById("sidebar-new-project-btn");
const sidebarProjectList = document.getElementById("sidebar-project-list");
const sidebarSettingsBtn = document.getElementById("sidebar-settings-btn");
const sidebarUserAvatar = document.getElementById("sidebar-user-avatar");
const sidebarProfileName = document.getElementById("sidebar-profile-name");
const sidebarProfileSub = document.getElementById("sidebar-profile-sub");

const settingsPopover = document.getElementById("settings-popover");
const settingsPanelMain = document.getElementById("settings-panel-main");
const settingsPanelTheme = document.getElementById("settings-panel-theme");
const settingsThemeBackBtn = document.getElementById("settings-theme-back-btn");
const themeSwatchGrid = document.getElementById("theme-swatch-grid");
const themeCustomColorInput = document.getElementById("theme-custom-color-input");

const startBtn = document.getElementById("start-btn");
const startBtnBottom = document.getElementById("start-btn-bottom");
const startScreen = document.getElementById("start-screen");
const driveScreen = document.getElementById("drive-screen");
const mainScreen = document.getElementById("main-screen");
const resultScreen = document.getElementById("result-screen");

const driveUserInfo = document.getElementById("drive-user-info");
const driveLogoutBtn = document.getElementById("drive-logout-btn");
const newProjectBtn = document.getElementById("new-project-btn");
const projectGrid = document.getElementById("project-grid");
const projectPagination = document.getElementById("project-pagination");

const userInfo = document.getElementById("user-info");
const logoutBtn = document.getElementById("logout-btn");
const backBtn = document.getElementById("back-btn");

const contentInput = document.getElementById("content-input");
const charCount = document.getElementById("char-count");
const contentHint = document.getElementById("content-hint");
const analyzeBtn = document.getElementById("analyze-btn");
const analyzeViewResultsBtn = document.getElementById("analyze-view-results-btn");
const analyzeProgressWrap = document.getElementById("analyze-progress-wrap");
const analyzeProgressStepConnect = document.getElementById("analyze-progress-step-0");
const analyzeProgressStepExtract = document.getElementById("analyze-progress-step-1");

// 1차 결과 탭 (결과 화면 안의 "1차 · 분석 결과" 탭)
const extractSections = document.getElementById("extract-sections");
const extractSummaryText = document.getElementById("extract-summary-text");
const extractStatCards = document.getElementById("extract-stat-cards");
const extractReviewBtn = document.getElementById("extract-review-btn");
const reportReviewBtn = document.getElementById("report-review-btn");

const resultTitleInfo = document.getElementById("result-title-info");
const resultProjectTitleEl = document.getElementById("result-project-title");
const backToAnalyzeBtnTop = document.getElementById("back-to-analyze-btn-top");
const analyzeTitleEl = document.getElementById("analyze-title");
const resultLogoutBtn = document.getElementById("result-logout-btn");
const newAnalysisBtn = document.getElementById("new-analysis-btn");
const statCards = document.getElementById("stat-cards");
const issueList = document.getElementById("issue-list");
const resultSummaryText = document.getElementById("result-summary-text");
const reportNote = document.getElementById("report-note");
// 검수 결과 창 전체가 공유하는 회차 필터 (전체 / 1회차 / 2회차 ...). 탭을 바꿔도 유지됩니다.
const roundFilterBarResult = document.getElementById("round-filter-bar-result");
const roundFilterArrowResult = document.getElementById("round-filter-arrow-result");
const analyzeRoundFilterWrap = document.getElementById("analyze-round-filter-wrap");
const roundFilterBarAnalyze = document.getElementById("round-filter-bar-analyze");
const roundFilterArrowAnalyze = document.getElementById("round-filter-arrow-analyze");
const sourceViewContent = document.getElementById("source-view-content");
const summaryList = document.getElementById("summary-list");
const visualContent = document.getElementById("visual-content");

const MIN_CHARS = 100;

// ---------- 브라우저 저장소 정리 (D12) ----------
// 브라우저에는 테마(모양·색상)와 사이드바 접힘만 남긴다. 예전 버전이 localStorage 에 두던
// 프로젝트·회차·브릿지 매핑은 이제 서버가 정본이라 지우기만 한다(이관하지 않는다 — D13).
const LEGACY_STORAGE_PREFIXES = [
  "worldview_projects_",
  "worldview_project_counter_",
  "glitch_bridge_state_v1",
  "glitch.backendCanon",
];
try {
  Object.keys(localStorage)
    .filter((k) => LEGACY_STORAGE_PREFIXES.some((p) => k.startsWith(p)))
    .forEach((k) => localStorage.removeItem(k));
} catch {
  // 저장소 접근이 막힌 환경(시크릿 모드 설정 등) — 지울 것도 없다
}

// ---------- 작업 화면 사이드바 ----------
const SIDEBAR_COLLAPSED_KEY = "worldview_sidebar_collapsed";
let sidebarCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";

function applySidebarCollapsedState() {
  appSidebar.classList.toggle("collapsed", sidebarCollapsed);
  document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
  // sidebartoggle_1 = 펼친 상태 아이콘, sidebartoggle_2 = 접힌 상태 아이콘
  sidebarToggleIcon.src = sidebarCollapsed
    ? "images/sidebartoggle_2.png"
    : "images/sidebartoggle_1.png";
}
applySidebarCollapsedState();

sidebarToggleBtn.addEventListener("click", () => {
  sidebarCollapsed = !sidebarCollapsed;
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed));
  applySidebarCollapsedState();
});

sidebarHamburgerBtn.addEventListener("click", () => {
  navigateTo("drive");
});

sidebarLogoBtn.addEventListener("click", () => {
  navigateTo("drive");
});

sidebarHomeBtn.addEventListener("click", () => {
  navigateTo("drive");
});

// 접혀 있을 때 "최근 항목"을 누르면 목록을 볼 수 있도록 사이드바를 펼칩니다.
sidebarRecentBtn.addEventListener("click", () => {
  if (sidebarCollapsed) {
    sidebarCollapsed = false;
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "false");
    applySidebarCollapsedState();
  }
});

// 검색창에 입력하면 프로젝트 목록을 제목 기준으로 필터링합니다 (서버 검색, 입력이 멈추면 요청).
let sidebarSearchTimer = 0;
sidebarSearchInput.addEventListener("input", () => {
  clearTimeout(sidebarSearchTimer);
  sidebarSearchTimer = setTimeout(() => renderSidebarProjects(sidebarSearchInput.value), 250);
});

// 사이드바의 "새 프로젝트" 아이콘: 어느 작업 화면에 있든 바로 이름 입력 모달을 띄웁니다.
sidebarNewProjectBtn.addEventListener("click", () => {
  openProjectNameModal();
});

// ---------- 설정 팝오버 ----------
sidebarSettingsBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  const willOpen = settingsPopover.classList.contains("hidden");
  if (willOpen) {
    showSettingsMainPanel();
  }
  settingsPopover.classList.toggle("hidden", !willOpen);
});

// 팝오버 바깥을 클릭하면 닫습니다.
document.addEventListener("click", (e) => {
  if (!settingsPopover.classList.contains("hidden") && !settingsPopover.contains(e.target) && e.target !== sidebarSettingsBtn) {
    settingsPopover.classList.add("hidden");
  }
});

function showSettingsMainPanel() {
  settingsPanelMain.classList.remove("hidden");
  settingsPanelTheme.classList.add("hidden");
}

function showSettingsThemePanel() {
  settingsPanelMain.classList.add("hidden");
  settingsPanelTheme.classList.remove("hidden");
  renderThemeSwatches();
}

document.querySelectorAll(".settings-menu-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    const action = btn.dataset.action;
    if (action === "theme") {
      showSettingsThemePanel();
    } else {
      // 계정 / 내 공개 링크 / 구독 관리는 아직 구현 전이라 자리만 잡아둡니다.
      // TODO: 실제 기능이 생기면 여기에 연결하세요.
      alert("아직 준비 중인 기능이에요.");
      settingsPopover.classList.add("hidden");
    }
  });
});

settingsThemeBackBtn.addEventListener("click", showSettingsMainPanel);

// ---------- 테마: 모양(밝게/어둡게/기기) ----------
const APPEARANCE_STORAGE_KEY = "worldview_appearance_mode";
const systemDarkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function applyAppearanceMode(mode) {
  // mode: "light" | "dark" | "system"
  const effectiveDark = mode === "dark" || (mode === "system" && systemDarkQuery.matches);
  document.documentElement.setAttribute("data-theme", effectiveDark ? "dark" : "light");

  document.querySelectorAll(".appearance-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
}

function loadSavedAppearanceMode() {
  return localStorage.getItem(APPEARANCE_STORAGE_KEY) || "system";
}

function saveAppearanceMode(mode) {
  localStorage.setItem(APPEARANCE_STORAGE_KEY, mode);
  applyAppearanceMode(mode);
}

// 기기 다크모드 설정이 실시간으로 바뀌면(예: 시스템 설정에서 전환) "기기" 모드일 때 즉시 반영
systemDarkQuery.addEventListener("change", () => {
  if (loadSavedAppearanceMode() === "system") applyAppearanceMode("system");
});

applyAppearanceMode(loadSavedAppearanceMode()); // 페이지 로드 시 바로 적용

document.querySelectorAll(".appearance-btn").forEach((btn) => {
  btn.addEventListener("click", () => saveAppearanceMode(btn.dataset.mode));
});

// ---------- 테마: 16가지 색상 (두 톤 프리셋 15개 + 커스텀 1개) ----------
const THEME_COLORS = [
  { name: "블루", teal: "#3b82f6", tealDark: "#2563eb" },
  { name: "그레이 블루", teal: "#64748b", tealDark: "#94a3b8" },
  { name: "스카이", teal: "#60a5fa", tealDark: "#93c5fd" },
  { name: "슬레이트", teal: "#475569", tealDark: "#64748b" },
  { name: "쿨 그레이", teal: "#6b7280", tealDark: "#9ca3af" },
  { name: "청록", teal: "#2f9e8f", tealDark: "#268376" },
  { name: "그린 (기본)", teal: "#22c55e", tealDark: "#16a34a" },
  { name: "세이지", teal: "#84a98c", tealDark: "#a3b899" },
  { name: "골드", teal: "#eab308", tealDark: "#facc15" },
  { name: "오렌지", teal: "#f97316", tealDark: "#fb923c" },
  { name: "테라코타", teal: "#c2410c", tealDark: "#ea580c" },
  { name: "핑크", teal: "#ec4899", tealDark: "#f472b6" },
  { name: "와인", teal: "#be123c", tealDark: "#e11d48" },
  { name: "모브", teal: "#a78bfa", tealDark: "#c4b5fd" },
  { name: "바이올렛", teal: "#7c3aed", tealDark: "#8b5cf6" },
];

const THEME_COLOR_STORAGE_KEY = "worldview_theme_color";

function applyThemeColor(teal, tealDark) {
  document.documentElement.style.setProperty("--teal", teal);
  document.documentElement.style.setProperty("--teal-dark", tealDark);
}

function loadSavedThemeColor() {
  try {
    const saved = JSON.parse(localStorage.getItem(THEME_COLOR_STORAGE_KEY) || "null");
    if (saved?.teal && saved?.tealDark) applyThemeColor(saved.teal, saved.tealDark);
  } catch (e) {
    console.error("테마 색상 불러오기 실패:", e);
  }
}
loadSavedThemeColor(); // 페이지 로드 시 저장된 색상을 바로 적용

function saveThemeColor(teal, tealDark) {
  applyThemeColor(teal, tealDark);
  localStorage.setItem(THEME_COLOR_STORAGE_KEY, JSON.stringify({ teal, tealDark }));
}

function renderThemeSwatches() {
  const currentTeal = getComputedStyle(document.documentElement).getPropertyValue("--teal").trim();
  const isPreset = THEME_COLORS.some((c) => c.teal === currentTeal);

  const presetCells = THEME_COLORS.map((c) => {
    const active = c.teal === currentTeal;
    return `
      <button type="button" class="theme-swatch-cell ${active ? "active" : ""}" data-teal="${c.teal}" data-teal-dark="${c.tealDark}" title="${escapeHtml(c.name)}">
        <span class="theme-swatch-circle ${active ? "active" : ""}" style="background:linear-gradient(90deg, ${c.teal} 50%, ${c.tealDark} 50%)"></span>
      </button>`;
  });

  const customCell = `
    <button type="button" class="theme-swatch-cell theme-swatch-custom-cell ${!isPreset ? "active" : ""}" id="theme-custom-swatch" title="커스텀 색상">
      <span class="theme-swatch-circle theme-swatch-custom ${!isPreset ? "active" : ""}" style="${!isPreset ? `background:${currentTeal}` : ""}">${isPreset ? "🎨" : ""}</span>
    </button>`;

  themeSwatchGrid.innerHTML = presetCells.join("") + customCell;

  themeSwatchGrid.querySelectorAll(".theme-swatch-cell[data-teal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      saveThemeColor(btn.dataset.teal, btn.dataset.tealDark);
      renderThemeSwatches();
    });
  });

  document.getElementById("theme-custom-swatch").addEventListener("click", () => {
    themeCustomColorInput.value = currentTeal.startsWith("#") ? currentTeal : "#2f9e8f";
    themeCustomColorInput.click();
  });
}

themeCustomColorInput.addEventListener("input", () => {
  const picked = themeCustomColorInput.value;
  // 커스텀 색은 살짝 어둡게 만든 색을 hover/dark 짝으로 함께 사용합니다.
  const darker = shadeColor(picked, -12);
  saveThemeColor(picked, darker);
  renderThemeSwatches();
});

// hex 색상을 percent 만큼 밝게(+)/어둡게(-) 조정
function shadeColor(hex, percent) {
  const num = parseInt(hex.replace("#", ""), 16);
  const clamp = (v) => Math.max(0, Math.min(255, v));
  const r = clamp(((num >> 16) & 0xff) + Math.round(2.55 * percent));
  const g = clamp(((num >> 8) & 0xff) + Math.round(2.55 * percent));
  const b = clamp((num & 0xff) + Math.round(2.55 * percent));
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

// 사이드바 "최근 항목": 서버 목록(updated_at 내림차순) 첫 페이지. 검색은 서버의 q 로 한다.
const SIDEBAR_PROJECT_LIMIT = 20;
let sidebarRenderSeq = 0;

async function renderSidebarProjects(searchQuery = "") {
  // 사용자 이니셜 아바타 + 이름/이메일
  const name = auth.currentUser?.displayName || "";
  sidebarUserAvatar.textContent = name.trim().charAt(0) || "?";
  sidebarUserAvatar.title = name;
  sidebarProfileName.textContent = name;
  sidebarProfileSub.textContent = auth.currentUser?.email || "";

  const query = searchQuery.trim();
  const seq = ++sidebarRenderSeq;
  let projects = [];
  try {
    projects = auth.currentUser ? (await store.listProjects(1, query, SIDEBAR_PROJECT_LIMIT)).items : [];
  } catch (e) {
    console.error("사이드바 프로젝트 목록 불러오기 실패:", e);
  }
  if (seq !== sidebarRenderSeq) return; // 더 최근 요청(검색어 입력 등)이 있으면 버린다

  if (projects.length === 0) {
    sidebarProjectList.innerHTML = `<li class="sidebar-project-empty">${
      query ? "검색 결과가 없어요." : "아직 프로젝트가 없어요."
    }</li>`;
    return;
  }

  sidebarProjectList.innerHTML = projects
    .map(
      (p) => `
      <li class="sidebar-project-item ${p.id === currentProjectId ? "active" : ""}" data-id="${p.id}" title="${escapeHtml(p.name)}">
        ${escapeHtml(p.name)}
      </li>`
    )
    .join("");

  sidebarProjectList.querySelectorAll(".sidebar-project-item").forEach((item) => {
    item.addEventListener("click", () => openProjectForEditing(item.dataset.id));
  });
}

// 사이드바는 작업 화면(세계관 분석하기 / 검수 결과)에서만 보여줍니다.
function updateSidebarVisibility(screen) {
  const shouldShow =
    (screen === "drive" || screen === "analyze" || screen === "result") && loggedInThisSession && auth.currentUser;
  appSidebar.classList.toggle("hidden", !shouldShow);
  document.body.classList.toggle("has-sidebar", shouldShow);
  if (shouldShow) renderSidebarProjects(sidebarSearchInput.value);
}

// 아직 서버에 올리지 않은 "새 파일" 목록. File 객체를 그대로 들고 있다가 "분석 시작" 때
// multipart 로 올린다 (txt/md/docx/pdf 텍스트 추출은 서버가 한다). 올리고 나면 목록에서
// 빠지고, 그 원고는 회차(서버)로 남는다. 새로 파일을 선택하면 목록에 계속 쌓인다 (누적).
const localFiles = { source: [], rules: [] };

// 지금 열려 있는 프로젝트의 id (서버 프로젝트 id). null이면 프로젝트를 열지 않은 상태입니다.
let currentProjectId = null;

// 결과 화면(검수 결과 창)에서 지금 보여주고 있는 회차 번호(서버 chapter_no, D14).
// "1차 · 분석 결과"와 "2차 · 검수결과" 두 탭이 모두 이 회차 기준으로 채워집니다.
let currentDisplayedChapterNo = null;
// 결과 화면 상단 회차 필터에서 고른 값: "all" | chapter_no
let selectedResultFilter = "all";

// 이번 페이지 진입(탭 열림) 중에 "시작하기" 버튼을 눌러 실제로 로그인에
// 성공했는지 여부. 이 값이 true일 때만 로그인 후 화면들을 보여줍니다.
let loggedInThisSession = false;

// ---------- 내 드라이브 화면 렌더링 ----------
const PROJECTS_PER_PAGE = 6;
let drivePage = 1;

function formatDate(ts) {
  const d = new Date(ts);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`;
}

// 내 드라이브: GET /projects?page=&page_size=6 (서버가 updated_at 내림차순으로 준다)
let driveRenderSeq = 0;

async function renderDriveScreen() {
  const seq = ++driveRenderSeq;
  let res;
  try {
    res = await store.listProjects(drivePage, "", PROJECTS_PER_PAGE);
    // 마지막 페이지의 카드를 지워서 페이지가 사라졌으면 마지막 페이지로 다시 받는다
    if (res.items.length === 0 && drivePage > 1 && res.total_pages >= 1 && drivePage > res.total_pages) {
      drivePage = res.total_pages;
      res = await store.listProjects(drivePage, "", PROJECTS_PER_PAGE);
    }
  } catch (e) {
    if (seq !== driveRenderSeq) return;
    console.error("프로젝트 목록 불러오기 실패:", e);
    projectGrid.innerHTML = `<p class="project-grid-empty">프로젝트 목록을 불러오지 못했어요. (${escapeHtml(e.message)})</p>`;
    projectPagination.innerHTML = "";
    return;
  }
  if (seq !== driveRenderSeq) return;

  const pageItems = res.items || [];
  const totalPages = Math.max(1, res.total_pages || 1);

  if (pageItems.length === 0) {
    projectGrid.innerHTML = `<p class="project-grid-empty">아직 작업한 프로젝트가 없어요. "새 프로젝트 만들기"로 시작해보세요.</p>`;
  } else {
    const fallbackAuthor = auth.currentUser?.displayName || "";
    projectGrid.innerHTML = pageItems
      .map(
        (p) => `
        <div class="project-card">
          <div class="project-card-title" data-id="${p.id}" title="클릭해서 이름 바꾸기">${escapeHtml(p.name)}</div>
          <div class="project-card-meta">
            <span class="project-avatar"></span>
            <div>
              <div class="project-author">${escapeHtml(p.author || fallbackAuthor)}</div>
              <div class="project-date">${formatDate(p.updated_at)}</div>
              <div class="project-chapter-meta">${escapeHtml(projectChapterSummary(p))}</div>
            </div>
          </div>
          <div class="project-card-actions">
            <button type="button" class="icon-btn" data-action="edit" data-id="${p.id}" title="열기">✏️</button>
            <button type="button" class="icon-btn" data-action="delete" data-id="${p.id}" title="삭제">🗑️</button>
          </div>
        </div>`
      )
      .join("");

    projectGrid.querySelectorAll('[data-action="edit"]').forEach((btn) => {
      btn.addEventListener("click", () => openProjectForEditing(btn.dataset.id));
    });
    projectGrid.querySelectorAll('[data-action="delete"]').forEach((btn) => {
      btn.addEventListener("click", () => deleteProjectById(btn.dataset.id));
    });
    projectGrid.querySelectorAll(".project-card-title").forEach((titleEl) => {
      titleEl.addEventListener("click", () => startEditingProjectTitle(titleEl));
    });
  }

  renderPagination(totalPages);
}

// 프로젝트 제목을 클릭하면 그 자리에서 바로 수정
function startEditingProjectTitle(titleEl) {
  const id = titleEl.dataset.id;
  const originalTitle = titleEl.textContent;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "project-card-title-input";
  input.value = originalTitle;
  titleEl.replaceWith(input);
  input.focus();
  input.select();

  let committed = false;
  const commit = async () => {
    if (committed) return;
    committed = true;
    const newTitle = input.value.trim() || originalTitle;
    if (newTitle !== originalTitle) {
      try {
        await store.renameProject(id, newTitle);
      } catch (e) {
        alert(`이름을 바꾸지 못했어요. (${e.message})`);
      }
    }
    renderDriveScreen();
    renderSidebarProjects(sidebarSearchInput.value);
  };
  const cancel = () => {
    if (committed) return;
    committed = true;
    renderDriveScreen();
  };

  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  });
}

// 카드의 회차 요약: "회차 3개 · 완료" (last_chapter_status = 가장 큰 회차 번호의 상태)
function projectChapterSummary(p) {
  if (!p.chapter_count) return "회차 없음";
  const label = chapterStatusLabel(p.last_chapter_status);
  return `회차 ${p.chapter_count}개${label ? ` · ${label}` : ""}`;
}

function renderPagination(totalPages) {
  if (totalPages <= 1) {
    projectPagination.innerHTML = "";
    return;
  }

  const buttons = [];
  buttons.push(
    `<button type="button" class="page-btn" data-page="prev" ${drivePage === 1 ? "disabled" : ""}>← Previous</button>`
  );

  for (let i = 1; i <= totalPages; i++) {
    // 페이지가 많으면 앞/뒤 일부와 현재 페이지 주변만 보여주고 나머지는 ... 로 생략합니다.
    const isEdge = i === 1 || i === totalPages;
    const isNear = Math.abs(i - drivePage) <= 1;
    if (isEdge || isNear) {
      buttons.push(
        `<button type="button" class="page-btn ${i === drivePage ? "active" : ""}" data-page="${i}">${i}</button>`
      );
    } else if (i === drivePage - 2 || i === drivePage + 2) {
      buttons.push(`<span class="page-ellipsis">…</span>`);
    }
  }

  buttons.push(
    `<button type="button" class="page-btn" data-page="next" ${drivePage === totalPages ? "disabled" : ""}>Next →</button>`
  );

  projectPagination.innerHTML = buttons.join("");

  projectPagination.querySelectorAll(".page-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const page = btn.dataset.page;
      if (page === "prev") drivePage = Math.max(1, drivePage - 1);
      else if (page === "next") drivePage = drivePage + 1;
      else drivePage = Number(page);
      renderDriveScreen();
    });
  });
}

// 프로젝트 열기: GET /projects/{id} + GET /projects/{id}/chapters
async function openProjectForEditing(id) {
  if (!auth.currentUser) return;
  let project;
  try {
    project = await store.openProject(id);
  } catch (e) {
    alert(`프로젝트를 열지 못했어요. (${e.message})`);
    return;
  }

  // 프로젝트를 열면 항상 "새 회차"로 이어서 작업 (기존 회차 기록은 그대로 보존).
  currentProjectId = project.id;
  // 진행 중인 작업이 있어도 진행 상황은 우측 하단 작업 창에서 보여주므로,
  // 이 화면의 진행 표시는 비워둡니다 (다른 프로젝트 작업이 여기 보이지 않게).
  setAnalyzeStage("idle");
  analyzeBtn.textContent = "◆ 분석 시작";
  // 칩 목록은 "아직 올리지 않은 새 파일"만 보여준다. 이미 올린 원고는 회차(서버)로 남아 있다.
  resetFormFields();

  navigateTo("analyze");
}

async function deleteProjectById(id) {
  if (!auth.currentUser) return;
  if (!confirm("이 프로젝트를 삭제할까요? 회차·분석 결과·캐논이 모두 지워지고 되돌릴 수 없어요.")) return;

  try {
    await store.deleteProject(id);
  } catch (e) {
    alert(`프로젝트를 삭제하지 못했어요. (${e.message})`);
    return;
  }
  if (currentProjectId === id) currentProjectId = null;
  renderDriveScreen();
  renderSidebarProjects(sidebarSearchInput.value);
}

function resetFormFields() {
  contentInput.value = "";
  localFiles.source = [];
  localFiles.rules = [];
  renderFileChipList("source", document.getElementById("source-filename"));
  renderFileChipList("rules", document.getElementById("rules-filename"));
  updateContentState();
}

// ---------- 새 프로젝트 이름 입력 모달 ----------
const projectNameModal = document.getElementById("project-name-modal");
const projectNameInput = document.getElementById("project-name-input");
const projectNameCancelBtn = document.getElementById("project-name-cancel-btn");
const projectNameConfirmBtn = document.getElementById("project-name-confirm-btn");

function openProjectNameModal() {
  projectNameInput.value = "";
  projectNameModal.classList.remove("hidden");
  projectNameInput.focus();
}

function closeProjectNameModal() {
  projectNameModal.classList.add("hidden");
}

newProjectBtn.addEventListener("click", openProjectNameModal);

projectNameCancelBtn.addEventListener("click", closeProjectNameModal);

// 오버레이의 빈 곳(모달 박스 바깥)을 클릭해도 닫히도록
projectNameModal.addEventListener("click", (e) => {
  if (e.target === projectNameModal) closeProjectNameModal();
});

projectNameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") confirmCreateProject();
  if (e.key === "Escape") closeProjectNameModal();
});

projectNameConfirmBtn.addEventListener("click", confirmCreateProject);

// 프로젝트 이름을 확정하고, 그 이름으로 프로젝트를 바로 생성한 뒤 분석 화면으로 이동합니다.
// (프로젝트 이름은 "분석 제목"과는 완전히 별개입니다.)
// 이름을 비우면 name 없이 POST /projects → 서버가 Project_N 을 붙인다.
let creatingProject = false;
async function confirmCreateProject() {
  if (!auth.currentUser || creatingProject) return;
  creatingProject = true;
  projectNameConfirmBtn.disabled = true;

  let created;
  try {
    created = await store.createProject(projectNameInput.value);
  } catch (e) {
    alert(`프로젝트를 만들지 못했어요. (${e.message})`);
    return;
  } finally {
    creatingProject = false;
    projectNameConfirmBtn.disabled = false;
  }

  closeProjectNameModal();
  resetFormFields();
  await openProjectForEditing(created.id);
}

// ---------- 페이지 진입 시 무조건 강제 로그아웃 ----------
// 로그인 팝업이 뜬 직후 signOut()이 뒤늦게 완료되며 로그인 자체를 취소시키는
// 경쟁 상태(race condition)를 막기 위해, 초기 로그아웃이 확실히 끝난 뒤에만
// "시작하기" 버튼을 누를 수 있도록 순서를 고정합니다.
let firstAuthCheck = true;

// 히어로 영역의 "시작하기"와, 스크롤해서 아래로 내려가면 나오는 두 번째 "시작하기"
// 버튼을 항상 같은 상태로 유지합니다.
const startButtons = [startBtn, startBtnBottom].filter(Boolean);

function setStartButtonsState(disabled, text) {
  startButtons.forEach((btn) => {
    btn.disabled = disabled;
    btn.textContent = text;
  });
}

setStartButtonsState(true, "준비 중...");

// 데모 로그인(?demo=1)일 때만 시작 화면에 작은 배지를 보여준다.
document.getElementById("demo-mode-badge")?.classList.toggle("hidden", !DEMO);

onAuthStateChanged(auth, (user) => {
  if (firstAuthCheck) {
    firstAuthCheck = false;
    if (user) {
      signOut(auth).finally(() => {
        setStartButtonsState(false, "시작하기");
      });
    } else {
      setStartButtonsState(false, "시작하기");
    }
    return;
  }

  if (!user && loggedInThisSession) {
    loggedInThisSession = false;
    currentProjectId = null;
    store.closeProject();
    resetTray();
    navigateTo("start");
  }
});

// ---------- 화면 전환 + 브라우저 뒤로가기/앞으로가기 지원 ----------
// 세계관 분석하기 / 검수 결과 화면 상단에 프로젝트 이름을 보여주기 위한 헬퍼입니다.
function getCurrentProjectTitle() {
  return (store.project?.id === currentProjectId && store.project?.name) || "세계관 분석하기";
}

function renderScreen(screen) {
  startScreen.classList.add("hidden");
  driveScreen.classList.add("hidden");
  mainScreen.classList.add("hidden");
  resultScreen.classList.add("hidden");

  updateSidebarVisibility(screen);

  const loggedIn = loggedInThisSession && auth.currentUser;

  if (screen === "drive" && loggedIn) {
    driveScreen.classList.remove("hidden");
    drivePage = 1;
    renderDriveScreen();
  } else if (screen === "analyze" && loggedIn && currentProjectId) {
    mainScreen.classList.remove("hidden");
    updateAnalyzeResultsTabState();
    renderAnalyzeRoundFilter();
    analyzeTitleEl.textContent = getCurrentProjectTitle();
    // 회차 상태는 서버가 바꾼다 — 화면에 돌아올 때마다 목록을 다시 받아 그린다
    if (store.project?.id === currentProjectId && store.chaptersAge > 1000) {
      store
        .refreshChapters()
        .then(() => {
          if (location.hash === "#analyze") {
            renderAnalyzeRoundFilter();
            updateAnalyzeResultsTabState();
          }
        })
        .catch((e) => console.warn("회차 목록 갱신 실패:", e));
    }
  } else if (screen === "result" && loggedIn && currentProjectId && currentDisplayedChapterNo != null) {
    // 검수 결과 창: "1차 · 분석 결과"와 "2차 · 검수결과" 탭을 모두 여기서 보여줍니다.
    resultScreen.classList.remove("hidden");
    resultProjectTitleEl.textContent = getCurrentProjectTitle();
  } else {
    startScreen.classList.remove("hidden");
  }
}

function navigateTo(screen) {
  history.pushState({ screen }, "", `#${screen}`);
  renderScreen(screen);
}

window.addEventListener("popstate", (e) => {
  const screen = e.state?.screen || "start";
  renderScreen(screen);
});

history.replaceState({ screen: "start" }, "", "#start");

// ---------- 세계관 분석하기 화면의 "이전 검수결과 →" 링크 ----------
// 현재 프로젝트에 회차가 1개 이상 있을 때만 보여주고, 누르면 마지막 회차의 결과 화면으로 갑니다.
function updateAnalyzeResultsTabState() {
  const hasChapters = store.project?.id === currentProjectId && store.chapters.length > 0;
  analyzeViewResultsBtn.classList.toggle("hidden", !hasChapters);
}

analyzeViewResultsBtn.addEventListener("click", () => {
  const chapters = store.chapters;
  if (analyzeViewResultsBtn.classList.contains("hidden") || chapters.length === 0) return;
  goToResultForChapter(chapters[chapters.length - 1].chapter_no);
});

function handleBackToAnalyze() {
  contentInput.value = "";
  updateContentState();
  navigateTo("analyze");
}

backToAnalyzeBtnTop.addEventListener("click", handleBackToAnalyze);

// ---------- 로그인 (팝업 방식) ----------
function handleStartClick() {
  setStartButtonsState(true, "로그인 중...");

  signInWithPopup(auth, provider)
    .then(async (result) => {
      console.log("로그인 성공:", result.user.email);
      await ensureBackendToken(); // 백엔드 JWT 교환이 끝나야 드라이브를 서버에서 받을 수 있다
      loggedInThisSession = true;
      navigateTo("drive"); // 로그인 후에는 내 드라이브부터 보여줍니다.
      // 새로고침·다른 기기에서 시작한 분석이 서버에서 아직 돌고 있으면 작업 창에 다시 올린다 (D16)
      restoreActiveJobs().catch((e) => console.warn("진행 중 작업 복원 실패:", e));
    })
    .catch((error) => {
      console.error("로그인 실패:", error.code, error.message);
      if (!error.code) {
        // Firebase 오류가 아니면 백엔드 토큰 교환 실패다
        signOut(auth);
        alert(`서버 로그인에 실패했어요. (${error.message})`);
      } else if (error.code === "auth/unauthorized-domain") {
        alert(
          "이 도메인이 Firebase에 등록되지 않았습니다.\n" +
          "Firebase 콘솔 > Authentication > Settings > 승인된 도메인에 현재 주소를 추가해주세요."
        );
      } else if (error.code === "auth/popup-blocked") {
        alert("브라우저가 팝업을 차단했습니다. 주소창의 팝업 차단 아이콘을 눌러 허용해주세요.");
      } else if (error.code !== "auth/popup-closed-by-user" && error.code !== "auth/cancelled-popup-request") {
        alert(`로그인 중 오류가 발생했습니다. (${error.code || error.message})`);
      }
    })
    .finally(() => {
      setStartButtonsState(false, "시작하기");
    });
}

startButtons.forEach((btn) => btn.addEventListener("click", handleStartClick));

function doLogout() {
  loggedInThisSession = false;
  currentProjectId = null;
  store.closeProject();
  resetTray();
  signOut(auth);
  navigateTo("start");
}

// 토큰 재교환까지 실패(로그인 만료) → 로그인 화면으로
onBackendAuthFailed(() => {
  if (!loggedInThisSession) return;
  doLogout();
  alert("로그인이 만료되었어요. 다시 로그인해주세요.");
});

driveLogoutBtn.addEventListener("click", doLogout);
logoutBtn.addEventListener("click", doLogout);
backBtn.addEventListener("click", doLogout);
resultLogoutBtn.addEventListener("click", doLogout);

newAnalysisBtn.addEventListener("click", () => {
  // 같은 프로젝트의 다음 회차로 이어서 작업합니다. 새 회차 번호는 서버 목록의 최대 + 1.
  contentInput.value = "";
  updateContentState();
  navigateTo("analyze");
});

// ---------- 탭/창을 닫을 때 로그아웃 (이중 안전장치) ----------
window.addEventListener("pagehide", () => {
  signOut(auth);
});

// ---------- 파일 업로드 ----------
// 파일은 브라우저에서 읽지 않는다. File 객체를 보관했다가 "분석 시작" 때 서버로 그대로 올린다.
// 같은 원고인지(중복)는 서버가 판단한다(D3) — 여기서는 같은 이름을 두 번 담지 않는 정도만 막는다.
function handleLocalFileSelected(fileList, kind, listEl) {
  for (const file of Array.from(fileList)) {
    if (localFiles[kind].some((f) => f.name === file.name)) continue;
    localFiles[kind].push({ name: file.name, label: file.name, file });
  }
  renderFileChipList(kind, listEl);
  updateAnalyzeButton();
}

function renderFileChipList(kind, listEl) {
  if (!listEl) return;

  listEl.innerHTML = localFiles[kind]
    .map(
      (file, index) => `
      <li class="file-chip">
        <span class="file-chip-name">📄 ${escapeHtml(file.label || file.name)}</span>
        <button type="button" class="file-chip-remove" data-kind="${kind}" data-index="${index}" title="제거">✕</button>
      </li>`
    )
    .join("");

  listEl.querySelectorAll(".file-chip-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.index);
      localFiles[kind].splice(idx, 1);
      renderFileChipList(kind, listEl);
      updateAnalyzeButton();
    });
  });
}

function setupDropzone(zoneId, inputId, filenameId, kind) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const filenameEl = document.getElementById(filenameId);

  zone.addEventListener("click", () => input.click());

  input.addEventListener("change", () => {
    if (input.files.length > 0) {
      handleLocalFileSelected(input.files, kind, filenameEl);
      input.value = "";
    }
  });

  ["dragenter", "dragover"].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
    });
  });

  zone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) handleLocalFileSelected(files, kind, filenameEl);
  });
}

setupDropzone("source-dropzone", "source-file", "source-filename", "source");
setupDropzone("rules-dropzone", "rules-file", "rules-filename", "rules");

// ---------- 직접 입력 글자 수 체크 ----------
function updateContentState() {
  const len = contentInput.value.length;
  charCount.textContent = `${len} / 최소 ${MIN_CHARS}자`;

  if (len >= MIN_CHARS) {
    contentHint.textContent = "입력이 완료되었습니다";
    contentHint.classList.add("ok");
  } else {
    contentHint.textContent = "최소 100자 이상 입력해주세요";
    contentHint.classList.remove("ok");
  }
  updateAnalyzeButton();
}

contentInput.addEventListener("input", updateContentState);

// "분석 시작"은 아직 올리지 않은 새 파일이 있거나, 직접 입력이 최소 글자 수를 넘었을 때만 눌립니다.
let analyzeSubmitting = false; // 업로드·추출 요청을 보내는 동안 (중복 클릭 방지)

function hasPendingInput() {
  return (
    localFiles.source.length + localFiles.rules.length > 0 || contentInput.value.trim().length >= MIN_CHARS
  );
}

function updateAnalyzeButton() {
  analyzeBtn.disabled = !hasPendingInput() || analyzeSubmitting || !currentProjectId;
  updateAnalyzeResultsTabState();
}

// ---------- 검수 결과 렌더링 ----------
// 이슈 = delta-view.js toIssues() 의 { id, chapterNo, status, category, title, description, quotes }.
// category 는 아래 CATEGORY_META 의 key 와 같다.
let currentAnalysisResult = [];

const CATEGORY_META = {
  character: { label: "인물", dot: "dot-blue" },
  time: { label: "시간", dot: "dot-yellow" },
  space: { label: "공간", dot: "dot-green" },
  event: { label: "사건", dot: "dot-red" },
  foreshadow: { label: "복선", dot: "dot-purple" },
  worldview: { label: "세계관", dot: "dot-teal" },
};

// 1차(추출) 결과 확인 화면에서 카테고리를 보여줄 순서. 흐름도의 박스 배치와 동일합니다.
// (세계관규칙 · 시간 · 공간 / 인물 · 사건 · 복선)
const NARRATIVE_CATEGORY_ORDER = ["worldview", "time", "space", "character", "event", "foreshadow"];
const NARRATIVE_CATEGORY_LABELS = {
  worldview: "세계관 규칙",
  time: "시간",
  space: "공간",
  character: "인물",
  event: "사건",
  foreshadow: "복선",
};

function renderAnalysisResults(issues, { emptyText } = {}) {
  currentAnalysisResult = issues;

  // ✕(무시)한 항목은 개수에서 빼고, 카드는 흐리게 남겨 되돌릴 수 있게 합니다.
  const counts = { character: 0, time: 0, space: 0, event: 0, foreshadow: 0, worldview: 0 };
  issues.forEach((issue) => {
    if (issue.status !== "dismissed" && counts[issue.category] !== undefined) counts[issue.category]++;
  });

  statCards.innerHTML = Object.entries(CATEGORY_META)
    .map(
      ([key, meta]) => `
      <div class="stat-card">
        <div class="stat-number">${counts[key]}</div>
        <div class="stat-label"><span class="dot ${meta.dot}"></span>${meta.label}</div>
      </div>`
    )
    .join("");

  renderReportSummary(emptyText);

  // 2차 검수결과는 내용을 고칠 수 없고, 항목별로 "✓ 모순 맞음" 또는 "✕ 무시"만 판정합니다.
  // 판정은 누르는 즉시 서버에 저장됩니다(PATCH /contradictions/{id}). 같은 버튼을 다시 누르면 되돌립니다.
  issueList.innerHTML = issues
    .map((issue, i) => {
      const meta = CATEGORY_META[issue.category] || { label: "기타", dot: "dot-blue" };
      const quotesHtml = (issue.quotes || [])
        .map(
          (q) => `
        <div class="quote-box">
          <span class="quote-tag">${escapeHtml(q.tag)}</span>
          <span>${escapeHtml(q.text)}</span>
        </div>`
        )
        .join("");
      return `
        <div class="issue-card ${issueStatusClass(issue.status)}" data-index="${i}">
          <div class="issue-header">
            <span class="dot ${meta.dot}"></span>${escapeHtml(meta.label)} · ${escapeHtml(issue.title)}
          </div>
          <p class="issue-desc">${escapeHtml(issue.description || "")}</p>
          <div class="quote-box-list">${quotesHtml}</div>
          <div class="extract-item-controls">
            <button type="button" class="issue-confirm-btn" title="모순이 맞아요 (다시 누르면 되돌리기)">✓</button>
            <button type="button" class="issue-remove" title="무시할게요 (다시 누르면 되돌리기)">✕</button>
          </div>
        </div>`;
    })
    .join("");

  issueList.querySelectorAll(".issue-confirm-btn").forEach((btn) => {
    btn.addEventListener("click", () => judgeIssue(btn, "confirmed"));
  });
  issueList.querySelectorAll(".issue-remove").forEach((btn) => {
    btn.addEventListener("click", () => judgeIssue(btn, "dismissed"));
  });
}

const issueStatusClass = (status) => (status === "confirmed" ? "confirmed" : status === "dismissed" ? "dismissed" : "");

function renderReportSummary(emptyText) {
  const issues = currentAnalysisResult || [];
  if (emptyText) {
    resultSummaryText.textContent = emptyText;
    return;
  }
  const confirmed = issues.filter((i) => i.status === "confirmed").length;
  const dismissed = issues.filter((i) => i.status === "dismissed").length;
  resultSummaryText.textContent =
    issues.length > 0
      ? `총 ${issues.length}건의 검토 항목을 발견했어요. (✓ 모순 맞음 ${confirmed} · ✕ 무시 ${dismissed})`
      : "발견된 모순이나 검토 항목이 없어요. 깔끔하네요!";
}

// ✓/✕ 판정 → 서버. 화면은 응답의 status 를 그대로 반영합니다.
async function judgeIssue(btn, target) {
  const card = btn.closest(".issue-card");
  const issue = currentAnalysisResult?.[Number(card?.dataset.index)];
  if (!card || !issue) return;

  const next = issue.status === target ? "pending" : target;
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    const updated = await store.setContradictionStatus(issue.chapterNo, issue.id, next);
    issue.status = updated.status;
    card.classList.remove("confirmed", "dismissed");
    const cls = issueStatusClass(issue.status);
    if (cls) card.classList.add(cls);
    renderAnalysisResultsCounts();
  } catch (e) {
    alert(`판정을 저장하지 못했어요. (${e.message})`);
  } finally {
    card.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

function renderAnalysisResultsCounts() {
  const counts = {};
  (currentAnalysisResult || []).forEach((issue) => {
    if (issue.status !== "dismissed") counts[issue.category] = (counts[issue.category] || 0) + 1;
  });
  statCards.querySelectorAll(".stat-card").forEach((el, i) => {
    const key = Object.keys(CATEGORY_META)[i];
    el.querySelector(".stat-number").textContent = counts[key] || 0;
  });
  renderReportSummary();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------- "1차 · 분석 결과" 탭 (결과 화면 안) ----------
// GET /chapters/{no}/result 의 canon_delta 를 화면 6분류로 바꿔(delta-view.js) 보여줍니다.
// 각 항목은 서버 정체성(data-category = 백엔드 카테고리, data-entity-key)을 DOM 에 들고 있고,
// "✏️ 수정하기 → ✓ 검토 완료로 표시"와 "✕ 삭제"는 그 자리에서 PATCH/DELETE 됩니다(D15).
// 고친 내용은 이 회차의 검토 메모(note/quote)로 저장되며 캐논 본문(자료정리·시각화)은 바뀌지 않습니다.
// 저장(saved)된 회차는 읽기 전용입니다(D2).
const extractViewItems = new Map(); // `${category}:${entityKey}` → delta-view 항목

function renderExtractStatCards(view) {
  extractStatCards.innerHTML = Object.entries(CATEGORY_META)
    .map(
      ([key, meta]) => `
      <div class="stat-card">
        <div class="stat-number">${(view?.[key] || []).length}</div>
        <div class="stat-label"><span class="dot ${meta.dot}"></span>${meta.label}</div>
      </div>`
    )
    .join("");
}

const EXTRACT_SUMMARY = {
  uploaded: "아직 1차 분석 전인 회차예요. 아래 버튼으로 1차 분석을 시작할 수 있어요.",
  extracting: "1차 추출 중이에요. 우측 하단 작업 창에서 진행 상황을 볼 수 있어요.",
  reviewing: "2차 검수 중이에요. 끝나면 \"2차 · 검수결과\" 탭에서 결과를 볼 수 있어요.",
  extracted:
    "1차 LLM이 추출한 데이터예요. 각 항목을 검토해서 그대로 둘지, 수정·삭제할지 정해주세요. 준비되면 아래 \"검토하기\"로 2차 모순 검토를 시작할 수 있어요.",
  reviewed:
    "검수는 끝났지만 아직 저장되지 않았어요. 아래 \"저장 재시도\"를 눌러주세요. (지금 항목을 고치면 검수 결과가 지워지고 다시 검토해야 해요)",
  saved: "저장된 회차예요. \"다시 검토하기\"로 2차 검수만 다시 돌릴 수 있어요.",
};

function extractItemKey(category, entityKey) {
  return `${category}:${entityKey}`;
}

async function renderExtractTab(chapterNo, isCurrent = () => true) {
  const chapter = store.chapter(chapterNo);
  extractViewItems.clear();
  renderReviewButton(chapter);

  if (!chapter) {
    extractSummaryText.textContent = "회차를 찾을 수 없어요.";
    renderExtractStatCards({});
    extractSections.innerHTML = "";
    return;
  }

  const status = chapter.status;
  extractSummaryText.textContent = EXTRACT_SUMMARY[status] || "";

  if (status === "uploaded" || isBusyStatus(status)) {
    renderExtractStatCards({});
    extractSections.innerHTML = "";
    return;
  }

  if (status === "failed") {
    renderExtractStatCards({});
    extractSections.innerHTML = `<p class="extract-empty">실패 사유를 불러오는 중...</p>`;
    let detail = null;
    try {
      detail = await store.getDetail(chapterNo);
    } catch (e) {
      console.warn("회차 상세 불러오기 실패:", e);
    }
    if (!isCurrent()) return;
    const stage = detail?.failed_stage === "review" ? "2차 검수" : "1차 추출";
    extractSummaryText.textContent = `${stage} 단계에서 실패한 회차예요. 아래 "다시 분석"으로 다시 시도할 수 있어요.`;
    extractSections.innerHTML = `
      <div class="extract-failed">
        <div class="extract-failed-title">⚠️ ${escapeHtml(stage)} 실패</div>
        <p class="extract-failed-detail">${escapeHtml(detail?.failed_detail || "실패 사유가 기록되지 않았어요.")}</p>
      </div>`;
    return;
  }

  // extracted / reviewed / saved
  extractSections.innerHTML = `<p class="extract-empty">1차 결과를 불러오는 중...</p>`;
  let result;
  try {
    result = await store.getResult(chapterNo);
  } catch (e) {
    if (isCurrent()) extractSections.innerHTML = `<p class="extract-empty">1차 결과를 불러오지 못했어요. (${escapeHtml(e.message)})</p>`;
    return;
  }
  if (!isCurrent()) return;

  const view = deltaToView(result.canon_delta, chapterNo);
  const readOnly = status === "saved";
  renderExtractStatCards(view);

  const note = readOnly
    ? `<p class="extract-edit-note is-locked">🔒 저장된 회차는 수정할 수 없어요.</p>`
    : `<p class="extract-edit-note">✏️ 수정한 내용은 이 회차의 추출 결과에 바로 반영되고, 검토 후 저장하면 시각화에도 반영돼요.</p>`;

  extractSections.innerHTML =
    note +
    NARRATIVE_CATEGORY_ORDER.map((key) => {
      const items = view[key] || [];
      const meta = CATEGORY_META[key];
      const itemsHtml =
        items.length > 0
          ? items
              .map((item) => {
                extractViewItems.set(extractItemKey(item.category, item.entityKey), item);
                return `
        <div class="extract-item" data-category="${escapeHtml(item.category)}" data-entity-key="${escapeHtml(item.entityKey)}" data-chapter-no="${chapterNo}">
          <div class="extract-item-title-label">${escapeHtml(item.title || `${NARRATIVE_CATEGORY_LABELS[key]} 항목`)}</div>
          <textarea class="extract-item-content" rows="2" placeholder="내용 요약" readonly>${escapeHtml(item.content || "")}</textarea>
          <textarea class="extract-item-quote" rows="2" placeholder="근거가 되는 원문 인용" readonly>${escapeHtml(item.quote || "")}</textarea>
          <div class="extract-item-controls">
            <button type="button" class="extract-item-edit-toggle" ${readOnly ? "disabled" : ""}>✏️ 수정하기</button>
            <button type="button" class="extract-item-remove" title="${readOnly ? "저장된 회차는 수정할 수 없어요" : "이 항목 삭제"}" ${readOnly ? "disabled" : ""}>✕</button>
          </div>
        </div>`;
              })
              .join("")
          : `<p class="extract-empty">추출된 항목이 없어요.</p>`;

      return `
      <div class="extract-section">
        <div class="extract-section-header"><span class="dot ${meta.dot}"></span>${escapeHtml(NARRATIVE_CATEGORY_LABELS[key])}</div>
        <div class="extract-item-list" data-category-list="${key}">${itemsHtml}</div>
      </div>`;
    }).join("");

  if (readOnly) return;

  extractSections.querySelectorAll(".extract-item-remove").forEach((btn) => {
    btn.addEventListener("click", () => deleteExtractItem(btn.closest(".extract-item")));
  });

  // 사용자 검토: 기본은 읽기 전용이고, "수정하기"를 눌러야 편집 가능한 상태로 바뀝니다.
  // "검토 완료로 표시"를 누르면 그 시점까지 입력한 내용이 곧바로 서버에 저장(PATCH)되고 읽기 전용으로 돌아갑니다.
  // (제목은 서버 항목의 이름이라 수정 대상이 아닙니다.)
  extractSections.querySelectorAll(".extract-item-edit-toggle").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const el = btn.closest(".extract-item");
      if (!el) return;
      const fields = el.querySelectorAll(".extract-item-content, .extract-item-quote");
      const nowEditing = el.classList.toggle("editing");
      fields.forEach((f) => (f.readOnly = !nowEditing));
      if (nowEditing) {
        fields[0]?.focus();
        btn.textContent = "✓ 검토 완료로 표시";
        return;
      }
      btn.disabled = true;
      btn.textContent = "저장 중...";
      await saveExtractItem(el);
      btn.disabled = false;
      btn.textContent = "✏️ 수정하기";
    });
  });
}

function extractItemOf(el) {
  return el ? extractViewItems.get(extractItemKey(el.dataset.category, el.dataset.entityKey)) : null;
}

// 수정 → PATCH /delta/{category}/{entity_key}. 고친 것이 없으면 보내지 않습니다.
async function saveExtractItem(el) {
  const item = extractItemOf(el);
  if (!item) return;
  const content = el.querySelector(".extract-item-content").value.trim();
  const quote = el.querySelector(".extract-item-quote").value.trim();
  if (content === (item.content || "").trim() && quote === (item.quote || "").trim()) return;

  const before = store.chapter(item.chapterNo)?.status;
  const body = toPatchBody(item, content, quote);
  try {
    const status = await store.updateDeltaItem(item, body);
    item.body = body;
    item.content = content;
    item.quote = quote;
    afterExtractEdit(item.chapterNo, before, status);
  } catch (e) {
    alert(`수정 내용을 저장하지 못했어요. (${e.message})`);
    selectResultRound(selectedResultFilter); // 서버 값으로 되돌린다
  }
}

// 삭제 → DELETE /delta/{category}/{entity_key}
async function deleteExtractItem(el) {
  const item = extractItemOf(el);
  if (!item) return;
  if (!confirm(`"${item.title}" 항목을 이 회차의 1차 결과에서 삭제할까요?`)) return;

  const before = store.chapter(item.chapterNo)?.status;
  try {
    const status = await store.deleteDeltaItem(item);
    if (afterExtractEdit(item.chapterNo, before, status)) return;
  } catch (e) {
    alert(`항목을 삭제하지 못했어요. (${e.message})`);
  }
  selectResultRound(selectedResultFilter);
}

// 편집 뒤: 서버가 reviewed → extracted 로 되돌렸다면 낡은 2차 결과가 지워졌다는 뜻 —
// 2차 탭을 비우고 "검토하기"를 다시 켠다(응답 뒤 다시 받은 회차 status 로 판단).
// 다시 그렸으면 true.
function afterExtractEdit(chapterNo, before, after) {
  if (before === after) return false;
  if (before === "reviewed" && after === "extracted") {
    showNotice({
      kind: "info",
      title: `${getCurrentProjectTitle()} · ${chapterNo}화`,
      message: "1차 결과를 고쳐서 이전 검수 결과가 지워졌어요. \"검토하기\"로 다시 검토해주세요.",
    });
  }
  selectResultRound(selectedResultFilter);
  return true;
}

// 검수 결과 창의 4개 탭(1차/2차/원문보기/시각화자료) 중 하나를 코드에서 강제로 활성화합니다.
// (분석 직후엔 "1차" 탭을, 검토 완료 직후엔 "2차" 탭을 자동으로 보여주는 데 씁니다.)
function activateResultTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
  const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  const panel = document.getElementById(`tab-${tabName}`);
  if (btn) btn.classList.add("active");
  if (panel) panel.classList.remove("hidden");
}

// ---------- 회차 필터 바 (전체 / 1회차 / 2회차 ...) ----------
// 검수결과 / 원문보기 / 시각화 자료 세 탭에서 공통으로 씁니다. 회차 번호는 서버 chapter_no 그대로(D14).
const parseChapterFilter = (v) => (v === "all" ? "all" : Number(v));

function renderRoundFilterInto(barEl, chapters, selected, onSelect) {
  if (!barEl) return;

  if (!chapters || chapters.length === 0) {
    barEl.innerHTML = "";
    return;
  }

  const buttons = [
    `<button type="button" class="round-filter-btn ${selected === "all" ? "active" : ""}" data-chapter-no="all">전체</button>`,
    ...chapters.map(
      (c) =>
        `<button type="button" class="round-filter-btn ${c.chapter_no === selected ? "active" : ""}" data-chapter-no="${c.chapter_no}" title="${escapeHtml(c.title || "")}">${c.chapter_no}회차</button>`
    ),
  ];

  barEl.innerHTML = buttons.join("");

  barEl.querySelectorAll(".round-filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => onSelect(parseChapterFilter(btn.dataset.chapterNo)));
  });
}

// 화살표를 누르면 필터 바를 옆으로 부드럽게 스크롤합니다 (회차가 많아져도 줄바꿈 없이).
function wireRoundFilterArrow(arrowEl, barEl) {
  if (!arrowEl || !barEl) return;
  arrowEl.addEventListener("click", () => {
    barEl.scrollBy({ left: 220, behavior: "smooth" });
  });
}

wireRoundFilterArrow(roundFilterArrowResult, roundFilterBarResult);
wireRoundFilterArrow(roundFilterArrowAnalyze, roundFilterBarAnalyze);

// ---------- 세계관 분석하기 화면의 회차 필터 바 (1회차 · 상태 / 2회차 · 상태 ...) ----------
// 현재 프로젝트의 회차(서버 목록)를 상태 배지와 함께 보여주고, 누르면 그 회차의 검수 결과 화면으로 이동합니다.
// 상태는 서버 chapters.status 그대로입니다. 회차가 없으면 필터 바를 숨깁니다.
const CHAPTER_STATE_CLASS = {
  saved: "is-reviewed",
  failed: "is-failed",
  extracting: "is-busy",
  reviewing: "is-busy",
};

function renderAnalyzeRoundFilter() {
  if (!analyzeRoundFilterWrap) return;

  const chapters = store.project?.id === currentProjectId ? store.chapters : [];

  if (chapters.length === 0) {
    analyzeRoundFilterWrap.classList.add("hidden");
    roundFilterBarAnalyze.innerHTML = "";
    return;
  }

  analyzeRoundFilterWrap.classList.remove("hidden");

  roundFilterBarAnalyze.innerHTML = chapters
    .map(
      (c) => `
        <button
          type="button"
          class="round-filter-btn round-filter-btn-with-state ${CHAPTER_STATE_CLASS[c.status] || "is-pending"}"
          data-chapter-no="${c.chapter_no}"
          title="${escapeHtml(c.title || "")}"
        >${c.chapter_no}회차 · ${escapeHtml(chapterStatusLabel(c.status))}</button>`
    )
    .join("");

  roundFilterBarAnalyze.querySelectorAll(".round-filter-btn-with-state").forEach((btn) => {
    btn.addEventListener("click", () => goToResultForChapter(Number(btn.dataset.chapterNo)));
  });
}

// ---------- 검수 결과 창으로 이동 ----------
// 흐름도의 두 결과물(1차 정리된 데이터 / 2차 모순 검토 결과)을 같은 화면 안에서 탭으로 나눠 보여줍니다.
// 아직 2차를 안 끝낸 회차는 "1차 · 분석 결과" 탭이, 검수·저장까지 끝난 회차는 "2차 · 검수결과" 탭이 열립니다.
function defaultResultTab(chapter) {
  return chapter && (chapter.status === "saved" || chapter.status === "reviewed") ? "report" : "extract";
}

function goToResultForChapter(chapterNo, preferredTab) {
  const chapters = store.chapters;
  if (chapters.length === 0) return;
  const chapter = chapterNo === "all" ? null : store.chapter(chapterNo);

  currentDisplayedChapterNo = chapter ? chapter.chapter_no : chapters[chapters.length - 1].chapter_no;

  navigateTo("result");
  activateResultTab(preferredTab || defaultResultTab(chapter || store.chapter(currentDisplayedChapterNo)));
  selectResultRound(chapter ? chapter.chapter_no : "all");
}

// 작업 창의 "결과 보기"나 중복 원고 안내처럼, 다른 프로젝트를 보고 있을 수도 있는 곳에서 회차를 열 때.
async function openChapterResult(projectId, chapterNo, preferredTab) {
  try {
    if (store.project?.id !== projectId) {
      await store.openProject(projectId);
      currentProjectId = projectId;
      resetFormFields();
    } else {
      await store.refreshChapters();
    }
  } catch (e) {
    alert(`회차를 열지 못했어요. (${e.message})`);
    return;
  }
  goToResultForChapter(chapterNo, preferredTab);
}

// 검수 결과 창 상단의 공유 회차 필터(전체 / 1회차 / 2회차 ...)에서 회차를 고르면,
// 4개 탭(1차/2차/원문보기/시각화자료) 내용을 전부 그 회차 기준으로 갱신합니다.
// 탭은 그대로 유지되고, 탭을 눌러 옮겨다녀도 골라둔 회차가 계속 유지됩니다.
// 탭 내용은 서버에서 받아오므로, 그 사이 다른 회차를 고르면 늦게 온 응답은 버립니다(isCurrent).
let resultRenderSeq = 0;

function selectResultRound(filter) {
  selectedResultFilter = filter;
  if (filter !== "all") currentDisplayedChapterNo = filter;
  resultProjectTitleEl.textContent = getCurrentProjectTitle();
  renderRoundFilterInto(roundFilterBarResult, store.chapters, filter, selectResultRound);

  const seq = ++resultRenderSeq;
  const isCurrent = () => seq === resultRenderSeq;
  renderExtractTab(currentDisplayedChapterNo, isCurrent);
  renderReportTab(filter, isCurrent);
  renderSourceTab(filter, isCurrent);
  selectedVisualFilter = filter;
  renderVisualIfShown();
}

// 시각화 탭은 보이고 있을 때만 서버에서 받아 그린다 (탭을 열 때 다시 그린다).
function renderVisualIfShown() {
  if (document.getElementById("tab-visual").classList.contains("hidden")) return;
  const activeCategoryBtn = document.querySelector(".category-btn.active");
  if (activeCategoryBtn) renderVisualCategory(activeCategoryBtn.dataset.category);
}

// ---------- 2차(검토) 시작 / 저장 재시도 / 다시 분석 ----------
// "1차 · 분석 결과" 탭 아래 버튼 하나가 회차 상태(서버 chapters.status)에 따라 할 일을 바꿉니다.
//   extracted → 검토하기      : POST /review (auto_save 기본) → 작업 창 폴링 → saved   (D4)
//   saved     → 다시 검토하기 : POST /review — 재업로드 없이 검수만 다시, 2차 목록이 새로 바뀜 (D5)
//   reviewed  → 저장 재시도   : auto_save 가 실패해 reviewed 에 멈춘 경우 POST /save
//   failed    → 다시 분석     : 추출 실패면 POST /extract, 검수 실패면 POST /review
//   uploaded  → 1차 분석 시작 : POST /extract
function chapterActionFor(chapter) {
  if (!chapter) return null;
  switch (chapter.status) {
    case "uploaded":
      return { label: "◆ 1차 분석 시작", run: "extract" };
    case "extracted":
      return { label: "◆ 검토하기 (2차 모순 검토 실행)", run: "review" };
    case "saved":
      return { label: "◆ 다시 검토하기 (2차 재실행)", run: "review" };
    case "reviewed":
      return { label: "◆ 저장 재시도", run: "save" };
    case "failed":
      return { label: "◆ 다시 분석", run: "retry" };
    case "extracting":
      return { label: "1차 추출 중...", run: null };
    case "reviewing":
      return { label: "2차 검토 중...", run: null };
    default:
      return null;
  }
}

// 1차 탭 맨 아래와 2차 탭 위쪽에 같은 버튼이 있다. 2차 탭 버튼은 "전체" 보기에서 숨긴다(어느 회차인지 모호).
function renderReviewButton(chapter) {
  const action = chapterActionFor(chapter);
  for (const btn of [extractReviewBtn, reportReviewBtn]) {
    const hide = !action || (btn === reportReviewBtn && selectedResultFilter === "all");
    btn.classList.toggle("hidden", hide);
    if (!action) continue;
    btn.textContent = action.label;
    btn.disabled = !action.run;
  }
}

extractReviewBtn.addEventListener("click", () => runChapterAction(currentDisplayedChapterNo));
reportReviewBtn.addEventListener("click", () => runChapterAction(currentDisplayedChapterNo));

async function runChapterAction(chapterNo) {
  const chapter = store.chapter(chapterNo);
  const action = chapterActionFor(chapter);
  if (!action?.run || !currentProjectId) return;

  // 요청 도중 다른 화면으로 옮겨가도 이 회차로 가도록 시작 시점에 고정합니다.
  const projectId = currentProjectId;
  const projectName = store.project?.name || "프로젝트";
  extractReviewBtn.disabled = true;
  reportReviewBtn.disabled = true;

  try {
    if (action.run === "save") {
      await store.save(projectId, chapterNo);
      showNotice({ kind: "done", title: `${projectName} · ${chapterNo}화`, message: "저장했어요." });
    } else {
      if (!(await checkPipelineReady(projectName))) return;
      let run = action.run;
      if (run === "retry") {
        const detail = await store.getDetail(chapterNo, { force: true });
        run = detail.failed_stage === "review" ? "review" : "extract";
      }
      const res = await startChapterJob(projectId, chapterNo, run, action.run === "retry");
      trackJob({ projectId, projectName, chapterNo, title: chapter.title, status: res.status });
    }
  } catch (e) {
    alert(`요청을 처리하지 못했어요. (${e.message})`);
  } finally {
    if (store.project?.id === projectId) {
      await store.refreshChapters().catch(() => {});
      refreshProjectViews(chapterNo);
    }
  }
}

// extract/review 요청. 이미 진행 중(409 + current_status)이면 그 작업을 지켜본다.
// 검수 실패 회차인데 추출 결과가 없으면(409) 추출부터 다시 한다(계약서 3장).
async function startChapterJob(projectId, chapterNo, run, fallbackToExtract) {
  try {
    return run === "review"
      ? await store.startReview(projectId, chapterNo)
      : await store.startExtract(projectId, chapterNo);
  } catch (e) {
    if (e.status === 409 && e.data?.current_status) return { status: e.data.current_status };
    if (e.status === 409 && run === "review" && fallbackToExtract) return store.startExtract(projectId, chapterNo);
    throw e;
  }
}

// 분석 서버 사전 점검(백엔드 → AI 서버). 점검 중에는 전체 화면 로딩, 실패하면 작업 창에 안내.
async function checkPipelineReady(projectName) {
  showEmbeddingLoader({ title: "서버 연결 중", sub: "분석 서버(AI)가 켜져 있는지 확인하고 있어요" });
  let health;
  try {
    health = await store.pipelineHealth();
  } catch (e) {
    health = { ok: false, message: e.message };
  } finally {
    hideEmbeddingLoader();
  }
  if (!health.ok) {
    showNotice({
      title: `${projectName} · 분석 시작`,
      message: "분석 서버에 연결할 수 없어 분석을 시작하지 않았어요.",
      detail: health.message,
    });
    return false;
  }
  if (health.message) console.info("[pipeline]", health.message);
  return true;
}

// ---- 검수결과 탭 (내용만 갱신, 필터 바는 selectResultRound가 공용으로 관리) ----
// reviewed/saved 회차의 GET /result 의 contradictions. "전체"는 검수가 끝난 회차를 모두 모은다.
async function renderReportTab(filter, isCurrent = () => true) {
  const chapters =
    filter === "all"
      ? store.chapters.filter((c) => c.status === "reviewed" || c.status === "saved")
      : [store.chapter(filter)].filter(Boolean);

  if (filter !== "all") {
    const c = chapters[0];
    if (!c || !(c.status === "reviewed" || c.status === "saved")) {
      reportNote.classList.add("hidden");
      renderAnalysisResults([], {
        emptyText:
          c?.status === "reviewing"
            ? "2차 검수 중이에요. 끝나면 여기에 결과가 나와요."
            : "아직 2차 검토 전이에요. 위의 \"검토하기\" 버튼을 눌러주세요.",
      });
      return;
    }
  }

  if (chapters.length === 0) {
    reportNote.classList.add("hidden");
    renderAnalysisResults([], { emptyText: "아직 검수가 끝난 회차가 없어요." });
    return;
  }

  resultSummaryText.textContent = "검수 결과를 불러오는 중...";
  let results;
  try {
    results = await Promise.all(chapters.map((c) => store.getResult(c.chapter_no)));
  } catch (e) {
    if (isCurrent()) renderAnalysisResults([], { emptyText: `검수 결과를 불러오지 못했어요. (${e.message})` });
    return;
  }
  if (!isCurrent()) return;

  const issues = chapters.flatMap((c, i) => toIssues(results[i].contradictions, c.chapter_no, c.title));
  reportNote.classList.remove("hidden");
  renderAnalysisResults(issues);
}

// ---- 원문보기 탭 ----
// GET /chapters/{no} 의 raw_text. 파일로 올린 원고는 서버가 파싱한 글자다(docx/pdf 포함).
async function renderSourceTab(filter, isCurrent = () => true) {
  const chapters = filter === "all" ? store.chapters : [store.chapter(filter)].filter(Boolean);
  sourceViewContent.innerHTML = `<p class="source-empty">원문을 불러오는 중...</p>`;

  let details;
  try {
    details = await Promise.all(chapters.map((c) => store.getDetail(c.chapter_no)));
  } catch (e) {
    if (isCurrent()) {
      sourceViewContent.innerHTML = `<p class="source-empty">원문을 불러오지 못했어요. (${escapeHtml(e.message)})</p>`;
    }
    return;
  }
  if (!isCurrent()) return;

  renderSourceEntries(
    details.map((d) => ({
      label: `${d.kind === "rules" ? "📘" : "📄"} ${d.chapter_no}회차 · ${d.title || "제목 없음"}${
        d.raw_path ? ` (${d.raw_path})` : ""
      }`,
      text: d.raw_text || "",
    }))
  );
  renderSourceSummary(filter, details);
  renderRoundHistory();
}

// "자료 요약": 보고 있는 회차(들)의 원문 정보
function renderSourceSummary(filter, details) {
  const totalChars = details.reduce((n, d) => n + (d.raw_text || "").length, 0);
  const rulesCount = details.filter((d) => d.kind === "rules").length;
  const rows = [
    ["보고 있는 회차", filter === "all" ? `전체 (${details.length}개)` : `${filter}회차`],
    ["원고 / 규칙 문서", `${details.length - rulesCount}개 / ${rulesCount}개`],
    ["원문 글자 수", `${totalChars.toLocaleString()}자`],
  ];
  if (filter !== "all" && details[0]) {
    rows.push(["상태", chapterStatusLabel(details[0].status)]);
    rows.push(["원본", details[0].raw_path || "직접 입력"]);
  }
  summaryList.innerHTML = rows
    .map(([label, value]) => `<li><span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span></li>`)
    .join("");
}

// ---- 시각화 자료 탭 ----
// "전체"면 현재 캐논, 회차를 고르면 그 회차가 캐논에 넣은 항목(저장 전이면 추출 결과)을 그립니다.
// 고른 회차는 selectResultRound 가 넣어줍니다. 데이터 고르기는 loadVisualHtml 참고.
let selectedVisualFilter = "all";

// ---------- 1차(추출) 진행 단계 표시 ----------
// "분석 시작"을 누르면 1차 LLM 호출만 실행되고, 그 결과는 바로 사용자에게 보여줘서
// 확인/수정을 받습니다 (2차 검토는 별도로, 사용자가 "검토하기"를 눌렀을 때 시작됩니다).
function setAnalyzeStage(stage) {
  if (!analyzeProgressWrap || !analyzeProgressStepExtract) return;

  if (stage === "idle") {
    analyzeProgressWrap.classList.add("hidden");
    analyzeProgressStepConnect?.classList.remove("active", "done");
    analyzeProgressStepExtract.classList.remove("active", "done");
    return;
  }

  analyzeProgressWrap.classList.remove("hidden");

  if (stage === "connect") {
    // 업로드 전에 백엔드 → AI 서버 연결부터 확인합니다 (checkPipelineReady).
    analyzeProgressStepConnect?.classList.add("active");
    analyzeProgressStepConnect?.classList.remove("done");
    analyzeProgressStepExtract.classList.remove("active", "done");
    analyzeBtn.textContent = "서버 연결 확인 중...";
  } else if (stage === "extract") {
    analyzeProgressStepConnect?.classList.remove("active");
    analyzeProgressStepConnect?.classList.add("done");
    analyzeProgressStepExtract.classList.add("active");
    analyzeProgressStepExtract.classList.remove("done");
    analyzeBtn.textContent = "1차 분석 중... (원문 정리)";
  } else if (stage === "done") {
    analyzeProgressStepExtract.classList.remove("active");
    analyzeProgressStepExtract.classList.add("done");
  }
}

// 원문보기 탭의 항목(파일별/회차별 접기·펼치기 카드) 렌더링을 담당합니다.
// 회차 필터 클릭(selectResultRound → renderSourceTab)에서 씁니다.
function renderSourceEntries(entries) {
  if (!entries || entries.length === 0) {
    sourceViewContent.innerHTML = `<p class="source-empty">내용이 없습니다.</p>`;
    return;
  }

  sourceViewContent.innerHTML = entries
    .map(
      (entry, index) => `
      <div class="source-entry">
        <div class="source-entry-header">
          <span class="source-entry-title">${escapeHtml(entry.label)}</span>
          <button type="button" class="source-entry-toggle" data-index="${index}">펼치기</button>
        </div>
        <pre class="source-entry-content collapsed" id="source-entry-content-${index}">${escapeHtml(entry.text)}</pre>
      </div>`
    )
    .join("");

  sourceViewContent.querySelectorAll(".source-entry-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const content = document.getElementById(`source-entry-content-${btn.dataset.index}`);
      const isCollapsed = content.classList.toggle("collapsed");
      btn.textContent = isCollapsed ? "펼치기" : "접기";
    });
  });
}

// 프로젝트 안에 쌓인 회차별 기록(1화, 2화, 3화...)을 목록으로 보여줍니다. (서버 회차 목록)
function renderRoundHistory() {
  const listEl = document.getElementById("round-history-list");
  if (!listEl) return;

  const chapters = store.chapters;
  if (chapters.length === 0) {
    listEl.innerHTML = `<li class="round-history-empty">아직 기록된 회차가 없어요.</li>`;
    return;
  }

  listEl.innerHTML = chapters
    .map((c) => {
      const done = c.status === "saved";
      const reviewed = done || c.status === "reviewed";
      return `
      <li class="round-history-item ${c.chapter_no === currentDisplayedChapterNo ? "current" : ""}">
        <span>${escapeHtml(String(c.chapter_no))}. ${escapeHtml(c.title || "제목 없음")} <em class="round-history-status ${
          done ? "done" : "pending"
        }">${escapeHtml(chapterStatusLabel(c.status))}</em></span>
        <span class="round-history-right">
          <span class="round-history-date">${formatDate(c.updated_at || c.created_at)}</span>
          <button
            type="button"
            class="round-history-review-btn"
            data-chapter-no="${c.chapter_no}"
          >${reviewed ? "결과 보기" : "1차 결과 보기"}</button>
        </span>
      </li>`;
    })
    .join("");

  listEl.querySelectorAll(".round-history-review-btn").forEach((btn) => {
    btn.addEventListener("click", () => goToResultForChapter(Number(btn.dataset.chapterNo)));
  });
}

// ---------- 시각화 자료 탭: 카테고리 선택 ----------
let visualRenderSeq = 0;

// 시각화의 유일한 출처는 캐논이다(D20). 렌더러는 canon-view.js 하나(D21).
//   전체          → canon?view=
//   N회차 saved   → canon?view=&chapter=N  (이 회차가 캐논에 넣은 행, 대체 표시 — D22)
//   N회차 저장 전 → result.canon_delta 를 같은 모양으로 (1차 탭과 같은 입력)
async function loadVisualHtml(category, filter) {
  const view = CANON_VIEW_OF[category];
  if (!view) return `<p class="visual-placeholder">준비 중인 항목이에요.</p>`;

  if (filter === "all") {
    // 사건의 등장 인물 id → 이름을 위해 인물 view 를 함께 받는다(캐시되므로 한 번만 간다)
    const [data, chars] = await Promise.all([store.getCanon(view), store.getCanon("characters")]);
    return renderCanonView(view, data, { mode: "all", names: characterNames(chars) });
  }

  const chapterNo = Number(filter);
  // 복선은 "전체"에서만 (D23)
  if (view === "foreshadowing") return renderCanonView(view, null, { mode: "chapter", chapterNo });

  const chapter = store.chapter(chapterNo);
  if (chapter && chapter.status !== "saved") {
    const result = await store.getResult(chapterNo);
    if (result?.canon_delta) {
      const views = deltaToCanonViews(result.canon_delta);
      const current = await store.getCanon("characters");
      return renderCanonView(view, views[view], {
        mode: "delta",
        chapterNo,
        names: characterNames(current, views.characters),
      });
    }
    // 재검수 중(saved → reviewing)이면 캐논에 이 회차 행이 그대로 있다. 그 밖엔 아직 그릴 것이 없다.
    if (chapter.status !== "reviewing") {
      return `<p class="visual-placeholder">${chapterNo}화는 아직 추출 결과가 없어요. (${escapeHtml(
        chapterStatusLabel(chapter.status)
      )})</p>`;
    }
  }

  const [data, chapterChars, currentChars] = await Promise.all([
    store.getCanon(view, { chapter: chapterNo }),
    store.getCanon("characters", { chapter: chapterNo }),
    store.getCanon("characters"),
  ]);
  // "버전 N · M화 설정을 대체"의 M = 대체된 버전의 출처 회차 → N-1화 시점 캐논에서 찾는다
  let prevSourceOf = {};
  if (chapterNo > 1 && hasReplacedRows(data)) {
    prevSourceOf = sourceChapterMap(await store.getCanon(view, { atChapter: chapterNo - 1 }));
  }
  return renderCanonView(view, data, {
    mode: "chapter",
    chapterNo,
    names: characterNames(currentChars, chapterChars),
    prevSourceOf,
  });
}

async function renderVisualCategory(category) {
  const seq = ++visualRenderSeq;
  const filter = selectedVisualFilter;
  visualContent.innerHTML = `<p class="visual-placeholder">시각화 자료를 불러오는 중...</p>`;

  let html;
  try {
    html = await loadVisualHtml(category, filter);
  } catch (e) {
    html = `<p class="visual-placeholder">시각화 자료를 불러오지 못했어요. (${escapeHtml(e.message)})</p>`;
  }
  if (seq === visualRenderSeq) visualContent.innerHTML = html;
}

bindCanonView(visualContent);

document.querySelectorAll(".category-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".category-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderVisualCategory(btn.dataset.category);
  });
});

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
    if (btn.dataset.tab === "visual") renderVisualIfShown();
  });
});

// ---------- 분석 시작 ----------
// 새로 담은 파일/텍스트를 순서대로(규칙 파일 → 원본 파일 → 직접 입력) 회차로 올리고(D1: 1개 = 회차 1개),
// 각각 1차 추출을 걸어 둡니다. 진행 상황은 우측 하단 작업 창(서버 폴링)이 보여주고,
// 이번에 올린 회차가 모두 끝났을 때 이 화면에 그대로 있으면 1차 탭으로 이동합니다.
analyzeBtn.addEventListener("click", startAnalysis);

const pendingBatches = []; // [{ projectId, chapters: Set<chapter_no>, first }]

function collectPendingEntries() {
  const entries = [
    ...localFiles.rules.map((f) => ({
      pending: ["rules", f],
      kind: "rules",
      // 파이프라인은 아직 제목이 [규칙]으로 시작하는지로 규칙 문서를 구분한다(계약서 3장)
      title: `[규칙] ${f.label}`,
      file: f.file,
      label: f.label,
    })),
    ...localFiles.source.map((f) => ({
      pending: ["source", f],
      kind: "narrative",
      title: f.label,
      file: f.file,
      label: f.label,
    })),
  ];
  const text = contentInput.value.trim();
  if (text.length >= MIN_CHARS) {
    entries.push({ kind: "narrative", title: "직접 입력", text, label: "직접 입력한 내용" });
  }
  return entries;
}

// 올린(또는 이미 있는) 항목을 "새 파일" 목록·입력창에서 뺀다
function dropPendingEntry(entry) {
  if (entry.pending) {
    const [kind, f] = entry.pending;
    localFiles[kind] = localFiles[kind].filter((x) => x !== f);
    renderFileChipList(kind, document.getElementById(kind === "rules" ? "rules-filename" : "source-filename"));
  } else if (entry.text != null && contentInput.value.trim() === entry.text) {
    contentInput.value = "";
    updateContentState();
  }
}

async function startAnalysis() {
  if (analyzeSubmitting || !currentProjectId || !hasPendingInput()) return;

  // 요청 도중 다른 프로젝트로 옮겨가도 이 프로젝트로 올라가도록 시작 시점에 고정합니다.
  const projectId = currentProjectId;
  const projectName = store.project?.name || "프로젝트";
  const isViewingThisProject = () => currentProjectId === projectId;
  const entries = collectPendingEntries();

  analyzeSubmitting = true;
  updateAnalyzeButton();
  setAnalyzeStage("connect");

  try {
    // 1) 서버 연결 사전 점검(백엔드 → AI 서버). 꺼져 있으면 업로드도 하지 않는다.
    if (!(await checkPipelineReady(projectName))) return;

    // 2) 순서대로 업로드 → 1차 추출 요청
    if (isViewingThisProject()) setAnalyzeStage("extract");
    let nextNo = store.project?.id === projectId ? store.nextChapterNo() : await store.fetchNextChapterNo(projectId);
    const started = [];
    for (const [i, entry] of entries.entries()) {
      if (isViewingThisProject()) analyzeBtn.textContent = `원고 올리는 중... (${i + 1}/${entries.length})`;
      const chapterNo = await uploadEntry(projectId, projectName, entry, nextNo);
      if (chapterNo == null) continue;
      nextNo = chapterNo + 1;
      if (isViewingThisProject()) dropPendingEntry(entry);
      if (await requestExtract(projectId, projectName, chapterNo, entry.title)) started.push(chapterNo);
    }
    if (started.length) pendingBatches.push({ projectId, chapters: new Set(started), first: started[0] });
    if (store.project?.id === projectId) await store.refreshChapters().catch(() => {});
  } finally {
    analyzeSubmitting = false;
    if (isViewingThisProject()) {
      analyzeBtn.textContent = "◆ 분석 시작";
      setAnalyzeStage("idle");
      renderAnalyzeRoundFilter();
    }
    updateAnalyzeButton();
  }
}

// 회차 1개 업로드. 성공하면 회차 번호, 건너뛰면 null.
async function uploadEntry(projectId, projectName, entry, chapterNo) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await store.uploadChapter(projectId, {
        chapterNo,
        title: entry.title,
        kind: entry.kind,
        file: entry.file,
        text: entry.text,
      });
      return chapterNo;
    } catch (e) {
      const existing = e.data?.existing_chapter_no;
      if (e.status === 409 && existing != null) {
        // 같은 원고가 이미 있다(서버가 원문 해시로 판단, D3) → 안내하고 넘어간다
        if (currentProjectId === projectId) dropPendingEntry(entry);
        showNotice({
          kind: "info",
          title: `${projectName} · ${entry.label}`,
          message: `이미 ${existing}화로 올라간 원고예요.`,
          actionLabel: `${existing}화 보기`,
          onAction: () => openChapterResult(projectId, existing),
        });
        return null;
      }
      if (e.status === 409 && attempt === 0) {
        // 회차 번호가 그새 쓰였다(다른 탭 등) → 서버 목록 기준으로 번호를 다시 잡아 한 번 더
        chapterNo = await store.fetchNextChapterNo(projectId);
        continue;
      }
      showNotice({ title: `${projectName} · ${entry.label}`, message: "원고를 올리지 못했어요.", detail: e.message });
      return null;
    }
  }
  return null;
}

// 1차 추출 요청 → 작업 창에 올린다. 이미 진행 중(409 + current_status)이면 그 작업을 지켜본다.
async function requestExtract(projectId, projectName, chapterNo, title) {
  try {
    const res = await store.startExtract(projectId, chapterNo);
    trackJob({ projectId, projectName, chapterNo, title, status: res.status });
    return true;
  } catch (e) {
    if (e.status === 409 && e.data?.current_status) {
      trackJob({ projectId, projectName, chapterNo, title, status: e.data.current_status });
      return true;
    }
    showNotice({
      title: `${projectName} · ${chapterNo}화`,
      message: "1차 추출을 시작하지 못했어요. 회차 화면에서 다시 분석할 수 있어요.",
      detail: e.message,
      actionLabel: `${chapterNo}화 보기`,
      onAction: () => openChapterResult(projectId, chapterNo),
    });
    return false;
  }
}

// ---------- 작업 창 ↔ 화면 ----------
// 끝난 작업 카드의 "결과 보기" → 그 회차의 결과 화면 (다른 프로젝트면 열어서)
setJobActionHandler((job) =>
  openChapterResult(job.projectId, job.chapterNo, job.kind === "review" ? "report" : "extract")
);

onJobFinished(async (job, result) => {
  if (store.project?.id === job.projectId) {
    const viewingThisChapter =
      location.hash === "#result" && currentProjectId === job.projectId && currentDisplayedChapterNo === job.chapterNo;
    try {
      await store.refreshChapters();
    } catch (e) {
      console.warn("회차 목록 갱신 실패:", e);
    }
    // 검토가 끝났을 때 그 회차 결과 화면에 있으면 "2차 · 검수결과" 탭을 보여준다
    if (viewingThisChapter && job.kind === "review" && (result?.status === "saved" || result?.status === "reviewed")) {
      activateResultTab("report");
    }
    refreshProjectViews(job.chapterNo);
  }

  // 이번 "분석 시작"으로 함께 올린 회차가 모두 끝났고 그 분석 화면에 그대로 있으면 1차 탭으로
  for (const batch of [...pendingBatches]) {
    if (batch.projectId !== job.projectId || !batch.chapters.has(job.chapterNo)) continue;
    batch.chapters.delete(job.chapterNo);
    if (batch.chapters.size > 0) continue;
    pendingBatches.splice(pendingBatches.indexOf(batch), 1);
    if (location.hash === "#analyze" && currentProjectId === batch.projectId) {
      goToResultForChapter(batch.first, "extract");
    }
  }
});

// 서버에서 회차 상태가 바뀐 뒤, 지금 보고 있는 화면만 다시 그린다.
function refreshProjectViews(changedNo) {
  if (location.hash === "#analyze") {
    renderAnalyzeRoundFilter();
    updateAnalyzeResultsTabState();
  } else if (location.hash === "#result") {
    if (selectedResultFilter === "all" || currentDisplayedChapterNo === changedNo) {
      selectResultRound(selectedResultFilter);
    } else {
      renderRoundFilterInto(roundFilterBarResult, store.chapters, selectedResultFilter, selectResultRound);
    }
  }
}

updateContentState();

// ============================================================
// 첫 화면: 점들이 모여 "Scope" 글자를 이뤘다가 흩어지길 반복하는 애니메이션
// ============================================================
(function setupScopeParticles() {
  const canvas = document.getElementById("scope-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let width = 0;
  let height = 0;
  let dpr = Math.min(window.devicePixelRatio || 1, 2);
  let particles = [];

  // "Scope" 글자 모양을 오프스크린 캔버스에 그린 뒤, 글자 위에 해당하는 픽셀
  // 좌표들을 일정 간격으로 뽑아냅니다. 이 좌표들이 점들이 "모였을 때"의 목표 위치가 됩니다.
  function sampleTextPoints() {
    const off = document.createElement("canvas");
    off.width = width;
    off.height = height;
    const offCtx = off.getContext("2d");
    offCtx.clearRect(0, 0, width, height);

    const fontSize = Math.min(width * 0.22, height * 0.4, 200);
    const textCenterY = height * 0.38; // 버튼(아래쪽)과 겹치지 않도록 중심보다 위에 그립니다.
    offCtx.fillStyle = "#000";
    offCtx.textAlign = "center";
    offCtx.textBaseline = "middle";
    offCtx.font = `800 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif`;
    offCtx.fillText("Scope", width / 2, textCenterY);

    const spacing = Math.max(3, Math.round(fontSize / 26));
    const { data } = offCtx.getImageData(0, 0, width, height);
    const points = [];
    for (let y = 0; y < height; y += spacing) {
      for (let x = 0; x < width; x += spacing) {
        const alpha = data[(y * width + x) * 4 + 3];
        if (alpha > 128) points.push({ x, y });
      }
    }
    return points;
  }

  function randomScatterPoint() {
    return {
      x: Math.random() * width,
      y: Math.random() * height,
    };
  }

  // 사용자가 테마에서 고른 강조색(--teal)을 캔버스에서 쓸 수 있도록 "r,g,b" 문자열로 읽어옵니다.
  function getThemeColorRGB() {
    const hex = getComputedStyle(document.documentElement).getPropertyValue("--teal").trim();
    const num = parseInt(hex.replace("#", ""), 16);
    if (Number.isNaN(num)) return "34,197,94"; // 파싱 실패 시 기본 초록
    return `${(num >> 16) & 255},${(num >> 8) & 255},${num & 255}`;
  }

  let themeRGB = "34,197,94";

  function rebuildParticles() {
    themeRGB = getThemeColorRGB();

    const textPoints = sampleTextPoints();
    // 점 개수가 너무 많으면 성능이 떨어지니 적당히 솎아냅니다.
    const MAX_PARTICLES = 420;
    const step = Math.max(1, Math.ceil(textPoints.length / MAX_PARTICLES));
    const chosen = textPoints.filter((_, i) => i % step === 0);

    particles = chosen.map((target) => ({
      home: randomScatterPoint(),
      target,
      radius: 1.2 + Math.random() * 2.6,
    }));

    // 글자가 다 모여있을 때도 배경에 옅게 남아있는 점들 (움직이지 않고 계속 떠 있음).
    // 색은 사용자가 테마에서 고른 강조색을 쓰고, 투명도만 8~22% 사이로 다양하게 줍니다.
    const AMBIENT_COUNT = 140;
    ambientDots = Array.from({ length: AMBIENT_COUNT }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      radius: 0.8 + Math.random() * 1.8,
      opacity: 0.08 + Math.random() * 0.14,
    }));
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    width = Math.round(rect.width);
    height = Math.round(rect.height);
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (width > 0 && height > 0) rebuildParticles();
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  // 한 사이클(전체 8.5초) 동안의 흐름: 흩어진 상태로 대기 → 모임 → 글자 상태로 대기 → 흩어짐
  const CYCLE_MS = 8500;
  const HOLD_SCATTERED = 0.06; // 0 ~ 6%: 흩어진 채로 잠깐 대기
  const GATHER_END = 0.42; // 6% ~ 42%: 모이는 중
  const HOLD_TEXT = 0.62; // 42% ~ 62%: 글자 상태로 대기
  const SCATTER_END = 0.98; // 62% ~ 98%: 흩어지는 중 (나머지는 대기)

  function getProgress(elapsedMs) {
    const t = (elapsedMs % CYCLE_MS) / CYCLE_MS;
    if (t < HOLD_SCATTERED) return 0;
    if (t < GATHER_END) return easeInOutCubic((t - HOLD_SCATTERED) / (GATHER_END - HOLD_SCATTERED));
    if (t < HOLD_TEXT) return 1;
    if (t < SCATTER_END) return 1 - easeInOutCubic((t - HOLD_TEXT) / (SCATTER_END - HOLD_TEXT));
    return 0;
  }

  let startTime = null;
  let ambientDots = [];

  function draw(now) {
    requestAnimationFrame(draw);

    // 시작 화면이 안 보일 때는(로그인 후 등) 그리기를 건너뛰어 자원을 아낍니다.
    if (startScreen.classList.contains("hidden") || width === 0) return;

    if (startTime === null) startTime = now;
    const progress = getProgress(now - startTime);

    ctx.clearRect(0, 0, width, height);

    // 1) 항상 옅게 떠 있는 배경 점들 (글자가 모여도 사라지지 않음) - 테마 색 사용
    for (const d of ambientDots) {
      ctx.beginPath();
      ctx.fillStyle = `rgba(${themeRGB}, ${d.opacity})`;
      ctx.arc(d.x, d.y, d.radius, 0, Math.PI * 2);
      ctx.fill();
    }

    // 2) 흩어졌다 모였다 하며 "Scope" 글자를 이루는 메인 점들
    ctx.fillStyle = "rgba(15, 23, 35, 0.82)";
    for (const p of particles) {
      const x = p.home.x + (p.target.x - p.home.x) * progress;
      const y = p.home.y + (p.target.y - p.home.y) * progress;
      ctx.beginPath();
      ctx.arc(x, y, p.radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  window.addEventListener("resize", resize);
  resize();
  requestAnimationFrame(draw);
})();

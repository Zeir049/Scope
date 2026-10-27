// ─────────────────────────────────────────────────────────────
//  백엔드 API 클라이언트 (계약서 docs/glitch_api_contract.md 매핑).
//  백엔드 호출은 전부 이 파일을 거친다. 화면 코드는 store.js 를 통해서만 쓴다.
//
//  인증: auth/backend-auth.js 가 configureAuth()로 토큰 공급자를 등록한다.
//  401 이 오면 토큰을 한 번 재교환해 같은 요청을 다시 보내고,
//  그래도 실패하면 onAuthFailed(로그인 화면으로)를 부른다.
// ─────────────────────────────────────────────────────────────
import { BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(status, detail, data) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
    this.data = data || null; // 409 의 existing_chapter_no / current_status 등 추가 필드
  }
}

const authHooks = {
  getToken: () => null,
  ensureToken: null, // 토큰이 없을 때 (재)교환해서 돌려준다
  refresh: null, // 401 뒤 토큰 재교환
  onAuthFailed: null, // 재교환도 실패 → 로그인 화면으로
};

export function configureAuth(hooks) {
  Object.assign(authHooks, hooks);
}

async function request(method, path, { body, auth = true, query, retried = false } = {}) {
  const url = new URL(BASE_URL + path, location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  const headers = {};
  if (auth) {
    let token = authHooks.getToken();
    if (!token && authHooks.ensureToken) {
      try {
        token = await authHooks.ensureToken();
      } catch {
        token = null;
      }
    }
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let payload;
  if (body instanceof FormData) {
    payload = body; // boundary 포함 Content-Type은 브라우저가 자동 설정
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(url, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "백엔드 서버에 연결할 수 없습니다. (서버 실행 여부 확인)");
  }

  const text = await res.text(); // 204 도 본문을 끝까지 읽어 요청이 중단(aborted)으로 남지 않게
  if (res.status === 204) return null;

  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!res.ok) {
    if (res.status === 401 && auth) {
      if (!retried && authHooks.refresh) {
        let ok = false;
        try {
          ok = !!(await authHooks.refresh());
        } catch {
          ok = false;
        }
        if (ok) return request(method, path, { body, auth, query, retried: true });
      }
      authHooks.onAuthFailed?.();
    }
    throw new ApiError(res.status, (data && data.detail) || `요청 실패 (HTTP ${res.status})`, data);
  }
  return data;
}

const chapterPath = (projectId, chapterNo) => `/projects/${projectId}/chapters/${chapterNo}`;

export const api = {
  // 구글 로그인(Firebase ID 토큰) → 자체 JWT 교환
  firebaseLogin: (idToken) =>
    request("POST", "/auth/firebase", { auth: false, body: { id_token: idToken } }),

  projects: {
    // 화면: 내 드라이브(page_size=6), 사이드바 최근 항목/검색
    list: (page = 1, q = "", page_size = 6) =>
      request("GET", "/projects", { query: { page, q, page_size } }),
    // name 을 비우면 서버가 Project_N 을 붙인다
    create: (name) => request("POST", "/projects", { body: name ? { name } : {} }),
    get: (id) => request("GET", `/projects/${id}`),
    update: (id, body) => request("PATCH", `/projects/${id}`, { body }),
    remove: (id) => request("DELETE", `/projects/${id}`),
  },

  chapters: {
    list: (projectId) => request("GET", `/projects/${projectId}/chapters`),
    get: (projectId, chapterNo) => request("GET", chapterPath(projectId, chapterNo)),
    remove: (projectId, chapterNo) => request("DELETE", chapterPath(projectId, chapterNo)),
    // 직접 입력 텍스트
    uploadText: (projectId, { chapter_no, title, text, kind = "narrative" }) =>
      request("POST", `/projects/${projectId}/chapters`, {
        body: { chapter_no, title, text, kind },
      }),
    // 원본 파일(multipart) — txt/md/docx/pdf 텍스트 추출은 서버가 한다
    uploadFile: (projectId, { chapter_no, title, file, kind = "narrative" }) => {
      const fd = new FormData();
      fd.append("chapter_no", String(chapter_no));
      if (title) fd.append("title", title);
      fd.append("kind", kind);
      fd.append("file", file, file.name);
      return request("POST", `/projects/${projectId}/chapters`, { body: fd });
    },
    // 1차 추출 시작 (202) → 상태 extracting
    extract: (projectId, chapterNo) => request("POST", `${chapterPath(projectId, chapterNo)}/extract`),
    // 2차 검수 시작 (202) → reviewing → reviewed → (auto_save) saved
    review: (projectId, chapterNo, opts = {}) =>
      request("POST", `${chapterPath(projectId, chapterNo)}/review`, { body: opts }),
    result: (projectId, chapterNo) => request("GET", `${chapterPath(projectId, chapterNo)}/result`),
    save: (projectId, chapterNo) => request("POST", `${chapterPath(projectId, chapterNo)}/save`),

    // 1차 추출 항목 편집. PATCH 는 항목 전체를 교체하므로 body 에 원본 필드를 모두 담는다.
    updateDeltaItem: (projectId, chapterNo, category, entityKey, body) =>
      request(
        "PATCH",
        `${chapterPath(projectId, chapterNo)}/delta/${category}/${encodeURIComponent(entityKey)}`,
        { body }
      ),
    deleteDeltaItem: (projectId, chapterNo, category, entityKey) =>
      request(
        "DELETE",
        `${chapterPath(projectId, chapterNo)}/delta/${category}/${encodeURIComponent(entityKey)}`
      ),
  },

  contradictions: {
    // 작가 판정: pending | confirmed(✓) | dismissed(✕)
    setStatus: (projectId, chapterNo, contradictionId, status) =>
      request("PATCH", `${chapterPath(projectId, chapterNo)}/contradictions/${contradictionId}`, {
        body: { status },
      }),
  },

  jobs: {
    // 진행 중(extracting|reviewing) 회차 — 작업 창 복원
    active: () => request("GET", "/jobs/active"),
  },

  pipeline: {
    // 분석 전 사전 점검: 백엔드 → AI 서버 연결. 실패도 200 + {ok:false, message}.
    health: () => request("GET", "/pipeline/health"),
  },

  canon: {
    // view: worldview | characters | timeline | spaces | events | foreshadowing
    // chapter=N: N화가 캐논에 넣은 행 전부(대체된 버전 포함) · at_chapter=N: N화 시점 캐논 · 둘 다 없으면 현재
    get: (projectId, view, { chapter, at_chapter } = {}) =>
      request("GET", `/projects/${projectId}/canon`, { query: { view, chapter, at_chapter } }),
  },
};

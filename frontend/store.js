// ─────────────────────────────────────────────────────────────
//  데이터 접근 한 곳 — 백엔드 API 호출 + 메모리 캐시.
//
//  화면(script.js)은 서버 데이터를 이 모듈로만 읽고 쓴다. 브라우저 저장소에는
//  아무것도 남기지 않는다(D12) — 새로고침하면 서버에서 다시 받는다.
//  진행 상태는 서버 chapters.status 가 유일한 진실이므로, 캐시는 "지금 열려 있는
//  프로젝트"의 회차 목록·상세·결과만 들고 있고 상태가 바뀌면 다시 받는다.
// ─────────────────────────────────────────────────────────────
import { api } from "./api.js";

const state = {
  project: null, // GET /projects/{id}
  chapters: [], // GET /projects/{id}/chapters (chapter_no 오름차순)
  details: new Map(), // chapter_no → GET /chapters/{no}
  results: new Map(), // chapter_no → GET /chapters/{no}/result
  canon: new Map(), // "view|chapter|at_chapter" → GET /projects/{id}/canon (회차가 저장되면 통째로 버린다)
  chaptersLoadedAt: 0, // 회차 목록을 마지막으로 받은 시각
};

function resetProjectCache() {
  state.chapters = [];
  state.details.clear();
  state.results.clear();
  state.canon.clear();
}

function requireProject() {
  if (!state.project) throw new Error("열려 있는 프로젝트가 없습니다.");
  return state.project.id;
}

export const store = {
  // ── 프로젝트 (내 드라이브) ──
  listProjects: (page = 1, q = "", pageSize = 6) => api.projects.list(page, q, pageSize),

  async createProject(name) {
    return api.projects.create((name || "").trim());
  },

  async renameProject(id, name) {
    const updated = await api.projects.update(id, { name });
    if (state.project?.id === id) state.project = updated;
    return updated;
  },

  async deleteProject(id) {
    await api.projects.remove(id);
    if (state.project?.id === id) store.closeProject();
  },

  /** 프로젝트 열기: 프로젝트 + 회차 목록. 다른 프로젝트 캐시는 버린다. */
  async openProject(id) {
    const [project, list] = await Promise.all([api.projects.get(id), api.chapters.list(id)]);
    state.project = project;
    resetProjectCache();
    state.chapters = sortChapters(list.items);
    state.chaptersLoadedAt = Date.now();
    return project;
  },

  closeProject() {
    state.project = null;
    resetProjectCache();
  },

  get project() {
    return state.project;
  },

  // ── 회차 ──
  get chapters() {
    return state.chapters;
  },

  /** 회차 목록을 받은 지 몇 ms 지났는지 (방금 받았으면 다시 받지 않으려고) */
  get chaptersAge() {
    return Date.now() - state.chaptersLoadedAt;
  },

  chapter(no) {
    return state.chapters.find((c) => c.chapter_no === Number(no)) || null;
  },

  /** 회차 목록을 다시 받는다. 상태가 바뀐 회차의 상세/결과 캐시는 버린다. */
  async refreshChapters() {
    const id = requireProject();
    const list = await api.chapters.list(id);
    if (state.project?.id !== id) return state.chapters; // 그새 다른 프로젝트를 열었다
    const before = new Map(state.chapters.map((c) => [c.chapter_no, c]));
    state.chapters = sortChapters(list.items);
    state.chaptersLoadedAt = Date.now();
    for (const c of state.chapters) {
      const old = before.get(c.chapter_no);
      if (!old || old.status !== c.status || old.updated_at !== c.updated_at) store.invalidate(c.chapter_no);
      if (touchesCanon(old?.status, c.status)) state.canon.clear();
    }
    // 저장된 회차가 사라졌으면(삭제) 캐논도 바뀌었다
    for (const [no, old] of before) {
      if (old.status === "saved" && !state.chapters.some((c) => c.chapter_no === no)) state.canon.clear();
    }
    return state.chapters;
  },

  /** 다음 회차 번호 = 현재 목록 최대 + 1 */
  nextChapterNo() {
    return state.chapters.reduce((m, c) => Math.max(m, c.chapter_no), 0) + 1;
  },

  invalidate(no) {
    state.details.delete(no);
    state.results.delete(no);
  },

  // ── 분석 요청 ──
  // 업로드·추출·검수·저장은 "시작한 프로젝트" id 를 명시적으로 받는다. 요청 도중에
  // 사용자가 다른 프로젝트를 열어도 엉뚱한 프로젝트로 가지 않게 하기 위해서다.
  // 캐시는 그 프로젝트가 지금 열려 있을 때만 고친다.

  /** 업로드. 파일이면 multipart(서버가 txt/md/docx/pdf 파싱), 아니면 JSON text. */
  async uploadChapter(projectId, { chapterNo, title, kind, file, text }) {
    const created = file
      ? await api.chapters.uploadFile(projectId, { chapter_no: chapterNo, title, file, kind })
      : await api.chapters.uploadText(projectId, { chapter_no: chapterNo, title, text, kind });
    if (state.project?.id === projectId) upsertChapter(created);
    return created;
  },

  /** 회차 번호 충돌(409) 뒤 다시 계산할 때: 서버 목록 기준 최대 + 1 */
  async fetchNextChapterNo(projectId) {
    const { items } = await api.chapters.list(projectId);
    if (state.project?.id === projectId) state.chapters = sortChapters(items);
    return (items || []).reduce((m, c) => Math.max(m, c.chapter_no), 0) + 1;
  },

  async startExtract(projectId, no) {
    const res = await api.chapters.extract(projectId, no);
    patchChapterStatus(projectId, no, res.status);
    return res;
  },

  /** 2차 검수(D4·D5). auto_save 기본 true — 서버가 saved 까지 간다. */
  async startReview(projectId, no, opts = {}) {
    const res = await api.chapters.review(projectId, no, opts);
    patchChapterStatus(projectId, no, res.status);
    return res;
  },

  /** reviewed 에서 멈춘 회차(auto_save 실패)의 저장 재시도. */
  async save(projectId, no) {
    const res = await api.chapters.save(projectId, no);
    patchChapterStatus(projectId, no, res.status);
    return res;
  },

  getDetail(no, { force = false } = {}) {
    return cached(state.details, no, force, (id) => api.chapters.get(id, no));
  },

  getResult(no, { force = false } = {}) {
    return cached(state.results, no, force, (id) => api.chapters.result(id, no));
  },

  /**
   * 1차 항목 수정/삭제 (D15). 서버가 reviewed → extracted 로 되돌릴 수 있으므로
   * 편집 뒤 회차 목록을 다시 받아 바뀐 status 를 돌려준다.
   */
  async updateDeltaItem(item, body) {
    const id = requireProject();
    await api.chapters.updateDeltaItem(id, item.chapterNo, item.category, item.entityKey, body);
    return afterDeltaEdit(item.chapterNo);
  },

  async deleteDeltaItem(item) {
    const id = requireProject();
    await api.chapters.deleteDeltaItem(id, item.chapterNo, item.category, item.entityKey);
    return afterDeltaEdit(item.chapterNo);
  },

  /** 모순 판정 ✓/✕ — 응답(갱신된 항목)을 결과 캐시에도 반영한다. */
  async setContradictionStatus(no, contradictionId, status) {
    const id = requireProject();
    const updated = await api.contradictions.setStatus(id, no, contradictionId, status);
    const r = await state.results.get(no)?.catch(() => null);
    if (r?.contradictions) {
      r.contradictions = r.contradictions.map((c) => (c.id === updated.id ? updated : c));
    }
    return updated;
  },

  /**
   * 캐논 view. 옵션 없음 = 현재 캐논("전체"), chapter = N화 기여(회차별 시각화), atChapter = N화 시점.
   * 회차가 saved 로 가거나 saved 에서 벗어나면 캐시를 통째로 버린다(refreshChapters·patchChapterStatus).
   */
  getCanon(view, { chapter = null, atChapter = null } = {}) {
    const key = `${view}|${chapter ?? ""}|${atChapter ?? ""}`;
    return cached(state.canon, key, false, (id) => api.canon.get(id, view, { chapter, at_chapter: atChapter }));
  },

  pipelineHealth: () => api.pipeline.health(),
};

// 회차별 캐시. 응답 대신 요청(Promise)을 담아, 여러 탭이 같은 회차를 동시에 그려도 요청은 한 번만 간다.
// 실패한 요청은 캐시에서 빼서 다음에 다시 시도한다.
function cached(map, no, force, fetcher) {
  const id = requireProject();
  if (!force && map.has(no)) return map.get(no);
  const p = fetcher(id);
  if (state.project?.id === id) {
    map.set(no, p);
    p.catch(() => {
      if (map.get(no) === p) map.delete(no);
    });
  }
  return p;
}

function sortChapters(items) {
  return [...(items || [])].sort((a, b) => a.chapter_no - b.chapter_no);
}

function upsertChapter(ch) {
  const rest = state.chapters.filter((c) => c.chapter_no !== ch.chapter_no);
  state.chapters = sortChapters([...rest, ch]);
  store.invalidate(ch.chapter_no);
}

// 캐논은 saved 회차들로만 만들어진다 — saved 로 들어가거나 saved 에서 나가면 바뀐다
function touchesCanon(before, after) {
  return before !== after && (before === "saved" || after === "saved");
}

function patchChapterStatus(projectId, no, status) {
  if (state.project?.id !== projectId) return;
  const ch = store.chapter(no);
  if (ch && touchesCanon(ch.status, status)) state.canon.clear();
  if (ch && status) ch.status = status;
  store.invalidate(no);
}

async function afterDeltaEdit(no) {
  store.invalidate(no);
  await store.refreshChapters();
  return store.chapter(no)?.status || null;
}

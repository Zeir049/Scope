// ─────────────────────────────────────────────────────────────
//  서버 데이터 → 화면 표시 변환 (화면 쪽만. 서버로 되돌리는 정렬·매칭은 없다).
//
//  1) canon_delta(7 카테고리) → 1차 탭 6분류 항목 {title, content, quote}
//     각 항목은 서버 정체성(category = 백엔드 키, entityKey, chapterNo)을 그대로 들고 다닌다.
//     화면은 이 값을 DOM data 속성에 실어 수정·삭제를 그 자리에서 PATCH/DELETE 한다.
//  2) contradictions → 2차 탭 이슈 카드
//  3) 회차 상태 라벨
//
//  수정 규칙: 1차 탭의 내용·인용 칸은 그 항목의 실제 필드를 보여주고, 고치면 그 필드를 교체한다
//  (EDIT_FIELDS). PATCH 는 canon_delta 안의 그 항목 하나만 바꾸고, 저장(save) 때 캐논에 병합돼
//  시각화에도 반영된다. 담을 필드가 없는 복선만 예전처럼 Delta.note/quote 에 담는다.
// ─────────────────────────────────────────────────────────────

// 화면 6분류의 표시 순서(= script.js NARRATIVE_CATEGORY_ORDER)
const FE_CATEGORIES = ["worldview", "time", "space", "character", "event", "foreshadow"];

// 화면 분류 → 백엔드 canon_delta 키. "인물"만 characters + relations 둘을 받는다
// (관계는 화면에 대응 칸이 없어서 인물 아래에 함께 보여준다).
const BE_KEYS_OF = {
  worldview: ["worldview"],
  time: ["timeline"],
  space: ["spaces"],
  character: ["characters", "relations"],
  event: ["events"],
  foreshadow: ["foreshadowing"],
};

const FORESHADOW_KIND = { setup: "복선 설치", payoff: "복선 회수" };

// 1차 탭 내용·인용 칸 ↔ 항목 필드 경로. 칸을 고치면 이 필드가 바뀐다.
// attrs 안의 키 이름은 LLM 원본 포맷 그대로(transform.py) — 시각화(canon-view.js)가 같은 키를 읽는다.
const SOURCE_TEXT = ["attrs", "source_text"];
const EDIT_FIELDS = {
  worldview: { content: ["detail"], quote: SOURCE_TEXT },
  characters: { content: ["attrs", "description"], quote: SOURCE_TEXT },
  relations: { content: ["attrs", "description"], quote: SOURCE_TEXT },
  timeline: { content: ["time_value"], quote: SOURCE_TEXT },
  spaces: { content: ["attrs", "description"], quote: SOURCE_TEXT },
  events: { content: ["attrs", "summary"], quote: SOURCE_TEXT },
  foreshadowing: { content: ["note"], quote: ["quote"] }, // 담을 데이터 필드가 없다
};

const getPath = (obj, path) => path.reduce((o, k) => (o == null ? undefined : o[k]), obj);

function setPath(obj, path, value) {
  let o = obj;
  for (const k of path.slice(0, -1)) {
    o[k] = o[k] && typeof o[k] === "object" ? { ...o[k] } : {};
    o = o[k];
  }
  o[path[path.length - 1]] = value;
}

// 백엔드 항목 → 화면에 보여줄 제목
const TITLE_OF = {
  worldview: (it) => it.item,
  characters: (it) => it.name,
  relations: (it) => `${it.from_char || "?"} → ${it.to_char || "?"}${it.relation ? ` (${it.relation})` : ""}`,
  timeline: (it) => it.scene_label || it.time_value,
  spaces: (it) => it.place || it.scene_label,
  events: (it) => it.label,
  foreshadowing: (it) => `${it.label}${it.kind ? ` · ${FORESHADOW_KIND[it.kind] || it.kind}` : ""}`,
};

/**
 * canon_delta(회차 1개) → 화면 6분류 항목.
 * @returns {{[feCategory: string]: Array<{title, content, quote, category, entityKey, chapterNo, body, baseContent}>}}
 *   category = 백엔드 카테고리(PATCH/DELETE 경로), body = 원본 항목(PATCH 는 전체 교체라 필요)
 */
export function deltaToView(canonDelta, chapterNo) {
  const out = {};
  for (const feKey of FE_CATEGORIES) {
    const items = [];
    for (const beKey of BE_KEYS_OF[feKey]) {
      for (const raw of canonDelta?.[beKey] || []) {
        const fields = EDIT_FIELDS[beKey];
        const base = getPath(raw, fields.content) ?? "";
        items.push({
          title: TITLE_OF[beKey](raw) || raw.entity_key,
          // 예전 방식(note 에만 담던 수정)이 남아 있으면 보여준다 — 다시 저장하면 필드로 옮겨진다.
          content: raw.note || base,
          quote: getPath(raw, fields.quote) ?? "",
          category: beKey,
          entityKey: raw.entity_key,
          chapterNo,
          body: raw,
          baseContent: base,
        });
      }
    }
    out[feKey] = items;
  }
  return out;
}

/**
 * 사용자가 고친 content/quote 를 PATCH 본문으로 만든다.
 * PATCH 는 항목 전체를 교체하므로 원본 body 를 깔고, 칸에 대응하는 필드(EDIT_FIELDS)만 바꾼다.
 */
export function toPatchBody(item, content, quote) {
  const fields = EDIT_FIELDS[item.category];
  const body = { ...item.body };
  // 예전 방식의 note 는 필드로 옮겼으니 비운다(복선은 note 가 곧 내용 칸)
  if (fields.content[0] !== "note") body.note = null;
  // 바뀐 칸만 쓴다 — 손대지 않은 빈 칸이 없던 키(null)를 만들지 않게
  for (const [path, value] of [[fields.content, content], [fields.quote, quote]]) {
    if ((value || null) !== (getPath(item.body, path) ?? null)) setPath(body, path, value || null);
  }
  return body;
}

// ── 모순(2차) ────────────────────────────────────────────────
// 백엔드 모순 type → 화면 6분류 (캐논 6뷰와 같은 체계)
function toCategory(type) {
  const t = (type || "").toLowerCase();
  if (t.includes("foreshadow")) return "foreshadow";
  if (t.includes("character") || t.includes("relation")) return "character";
  if (t.includes("time")) return "time";
  if (t.includes("space") || t.includes("place")) return "space";
  if (t.includes("event")) return "event";
  return "worldview"; // setting/knowledge/item 등 나머지는 "세계관"으로
}

/** contradictions → 2차 탭 이슈 카드. id/chapterNo/status 는 ✓/✕ PATCH 에 쓴다. */
export function toIssues(contradictions, chapterNo, chapterTitle) {
  return (contradictions || []).map((c) => {
    const quotes = [];
    if (c.span?.quote) quotes.push({ tag: `현재 ${chapterNo}화`, text: c.span.quote });
    if (c.conflict_ref?.quote)
      quotes.push({
        tag: c.conflict_ref.chapter_no != null ? `${c.conflict_ref.chapter_no}화` : "이전 회차",
        text: c.conflict_ref.quote,
      });
    return {
      id: c.id,
      chapterNo,
      status: c.status || "pending",
      category: toCategory(c.type),
      title: chapterTitle ? `${chapterNo}화 · ${chapterTitle}` : `${chapterNo}화`,
      description: c.explanation || "",
      quotes,
    };
  });
}

// ── 회차 상태 라벨 (chapters.status 가 유일한 진실 — 화면은 보여주기만) ──
const CHAPTER_STATUS_LABELS = {
  uploaded: "분석 전",
  extracting: "추출 중",
  extracted: "1차 확인 대기",
  reviewing: "검수 중",
  reviewed: "저장 대기",
  saved: "완료",
  failed: "실패",
};

export function chapterStatusLabel(status) {
  return CHAPTER_STATUS_LABELS[status] || status || "";
}

export const isBusyStatus = (status) => status === "extracting" || status === "reviewing";

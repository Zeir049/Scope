// ─────────────────────────────────────────────────────────────
//  시각화 자료 탭의 유일한 렌더러 (D20·D21) — 캐논 6뷰(GET /projects/{id}/canon?view=) 모양을 그린다.
//
//  "전체"   = canon?view=            (현재 캐논)
//  "N회차" = canon?view=&chapter=N  (N화가 캐논에 넣은 행 — 이후 대체된 버전 포함)
//            저장 전 회차는 캐논에 행이 없으므로 result.canon_delta 를 같은 모양으로 바꿔 그린다(deltaToCanonViews).
//
//  항목마다 entity_key(회차 사이에서 같은 항목을 잇는 키)·source_chapter·version·is_current·
//  superseded_at_chapter 가 있고, 복선을 뺀 탭에는 attrs(LLM 추출 원본의 부가 정보, 키 이름 그대로)가 있다.
//  0005 이전에 저장된 행은 attrs 가 null 이거나 인물 traits 가 문자열 배열이다 — 둘 다 받는다.
// ─────────────────────────────────────────────────────────────

// 화면 카테고리 버튼(data-category) → 캐논 view
export const CANON_VIEW_OF = {
  worldview: "worldview",
  character: "characters",
  time: "timeline",
  space: "spaces",
  event: "events",
  foreshadow: "foreshadowing",
};

const VIEW_LABELS = {
  worldview: "세계관",
  characters: "인물",
  timeline: "시간",
  spaces: "공간",
  events: "사건",
  foreshadowing: "복선",
};

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ── attrs 표현 헬퍼 (옛 회차별 렌더러에서 옮겨 옴) ──
function certaintyToStars(certainty) {
  const map = { explicit: "★★★", inferred: "★★☆", uncertain: "★☆☆" };
  return map[String(certainty).toLowerCase()] || "☆☆☆";
}

const CERTAINTY_LABEL = { explicit: "명시", inferred: "추론", uncertain: "불확실" };

function certaintyBadge(certainty) {
  if (!certainty) return "";
  const label = CERTAINTY_LABEL[String(certainty).toLowerCase()] || certainty;
  return `<span class="wv-certainty" title="신뢰도: ${esc(label)}">${esc(certaintyToStars(certainty))}</span>`;
}

function sentimentToKorean(sentiment) {
  const map = { positive: "긍정", negative: "부정", neutral: "중립", mixed: "복합" };
  return map[String(sentiment).toLowerCase()] || "중립";
}

const SENTIMENT_COLOR = { positive: "#22c55e", negative: "#ef4444", neutral: "#9aa0a8", mixed: "#a855f7" };
function sentimentToColor(sentiment) {
  return SENTIMENT_COLOR[String(sentiment).toLowerCase()] || SENTIMENT_COLOR.neutral;
}

const AVATAR_PALETTE = ["#3b82f6", "#a855f7", "#14b8a6", "#f97316", "#ec4899", "#22c55e", "#eab308", "#6366f1"];
function stringToPaletteColor(str) {
  const s = String(str || "");
  let hash = 0;
  for (let i = 0; i < s.length; i++) hash = s.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

function avatarInitial(name) {
  const trimmed = String(name || "").trim();
  return trimmed ? trimmed[0] : "?";
}

function avatarStyle(key) {
  const c = stringToPaletteColor(key);
  return `background:${c}22;color:${c};border-color:${c}66`;
}

// 근거 원문: 길어서 접어 둔다
function sourceBox(sourceText) {
  if (!sourceText) return "";
  return `
    <details class="canon-source">
      <summary>근거 원문</summary>
      <div class="quote-box"><span class="quote-tag">원문</span><span>${esc(sourceText)}</span></div>
    </details>`;
}

// 렌더러가 따로 그리는 attrs 키 — 나머지(예상 못 한 키)만 "속성" 칩으로 나열한다
const ATTRS_RENDERED = [
  "source_text",
  "certainty",
  "description",
  "aliases",
  "traits",
  "first_appearance_event_id",
  "relationship_type",
  "sentiment",
  "summary",
  "cause",
  "result",
  "main_actor_character_id",
  "participant_character_ids",
];

function attrsList(attrs) {
  if (!attrs || typeof attrs !== "object") return "";
  const rows = Object.entries(attrs)
    .filter(
      ([k, v]) => !ATTRS_RENDERED.includes(k) && v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)
    )
    .map(
      ([k, v]) =>
        `<span class="wv-trait-chip" title="${esc(k)}">${esc(
          Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : v
        )}</span>`
    )
    .join("");
  return rows ? `<div class="wv-chip-row"><span class="wv-chip-label">속성</span>${rows}</div>` : "";
}

// ── 버전 표시 (D22) ──
// ctx.mode: "all"(현재 캐논) | "chapter"(N화 기여) | "delta"(저장 전 추출 결과)
// ctx.prevSourceOf: entity_key → 대체된 이전 버전의 source_chapter (N-1화 시점 캐논에서)
function metaRow(it, ctx, extra = "") {
  const parts = [];
  if (ctx.mode === "all") {
    if (it.source_chapter != null) parts.push(`출처 ${it.source_chapter}화`);
    if (it.version > 1) parts.push(`버전 ${it.version}`);
  } else if (ctx.mode === "chapter") {
    if (it.version > 1) {
      const prev = ctx.prevSourceOf?.[it.entity_key];
      parts.push(`버전 ${it.version} · ${prev != null ? `${prev}화` : "이전"} 설정을 대체`);
    }
    if (it.superseded_at_chapter != null) parts.push(`이후 ${it.superseded_at_chapter}화에서 대체됨`);
  }
  if (extra) parts.push(extra);
  const key = it.entity_key ? `<code class="canon-key">${esc(it.entity_key)}</code>` : "";
  return `<div class="wv-meta-row canon-meta">${esc(parts.join(" · "))}${key}</div>`;
}

const supersededClass = (it) => (it.superseded_at_chapter != null ? " canon-superseded" : "");
const versionClass = (it, ctx) => (ctx.mode === "chapter" && it.version > 1 ? " canon-replaces" : "");
const cardClass = (it, ctx) => supersededClass(it) + versionClass(it, ctx);

function emptyHtml(view, ctx) {
  const label = VIEW_LABELS[view] || "";
  if (ctx.mode === "chapter")
    return `<p class="visual-placeholder">${ctx.chapterNo}화가 캐논에 넣은 ${esc(label)} 항목이 없어요. (이전 회차와 같은 설정은 이 회차의 기여로 잡히지 않아요)</p>`;
  if (ctx.mode === "delta") return `<p class="visual-placeholder">${ctx.chapterNo}화 추출 결과에 ${esc(label)} 항목이 없어요.</p>`;
  return `<p class="visual-placeholder">아직 저장된 ${esc(label)} 캐논이 없어요. 회차를 검토·저장하면 채워집니다.</p>`;
}

// 같은 entity_key 의 여러 버전(chapter=N)은 키 순 → 버전 순으로 붙여 보여준다
function byKeyThenVersion(a, b) {
  return String(a.entity_key).localeCompare(String(b.entity_key)) || (a.version ?? 0) - (b.version ?? 0);
}

// order_index 는 회차마다 1부터 다시 센다 — "전체"에서 회차가 섞이지 않게 출처 회차 → 순서로 정렬
function byChapterThenOrder(a, b) {
  return (a.source_chapter ?? 0) - (b.source_chapter ?? 0) || (a.order_index ?? 0) - (b.order_index ?? 0);
}

const nameOf = (ctx, id) => ctx.names?.[id] || id;

// 관계도 원(지름 68) 안에 들어가게 — 전체 이름은 <title> 툴팁과 카드에
const shortName = (name) => {
  const s = String(name || "");
  return s.length > 6 ? `${s.slice(0, 5)}…` : s;
};

// ── 6 렌더러 ──
function worldviewHtml(data, ctx) {
  const items = data.items || [];
  if (!items.length) return emptyHtml("worldview", ctx);
  return `<div class="issue-list">${items
    .map((it) => {
      const a = it.attrs || {};
      return `
      <div class="issue-card${cardClass(it, ctx)}">
        <div class="issue-header"><span class="dot dot-teal"></span><span>${esc(it.item || "내용 없음")}</span>${certaintyBadge(a.certainty)}</div>
        ${it.detail ? `<p class="issue-desc">${esc(it.detail)}</p>` : ""}
        ${attrsList(a)}
        ${sourceBox(a.source_text)}
        ${metaRow(it, ctx)}
      </div>`;
    })
    .join("")}</div>`;
}

function timelineHtml(data, ctx) {
  const items = [...(data.items || [])].sort(byChapterThenOrder);
  if (!items.length) return emptyHtml("timeline", ctx);
  return `<div class="timeline">${items
    .map((it, i) => {
      const a = it.attrs || {};
      return `
      <div class="timeline-item${cardClass(it, ctx)}">
        <div class="timeline-rail">
          <span class="timeline-node">${esc(String(it.order_index ?? i + 1))}</span>
          ${i < items.length - 1 ? `<span class="timeline-line"></span>` : ""}
        </div>
        <div class="timeline-content">
          <div class="timeline-header">
            <span class="timeline-expression">${esc(it.time_value || it.scene_label || "내용 없음")}</span>
            ${certaintyBadge(a.certainty)}
          </div>
          ${a.description ? `<p class="issue-desc">${esc(a.description)}</p>` : ""}
          ${attrsList(a)}
          ${sourceBox(a.source_text)}
          ${metaRow(it, ctx, it.scene_label && it.time_value ? it.scene_label : "")}
        </div>
      </div>`;
    })
    .join("")}</div>`;
}

function spacesHtml(data, ctx) {
  const items = data.items || [];
  if (!items.length) return emptyHtml("spaces", ctx);
  return `<div class="issue-list">${items
    .map((it) => {
      const a = it.attrs || {};
      return `
      <div class="issue-card${cardClass(it, ctx)}">
        <div class="issue-header"><span class="dot dot-green"></span><span>${esc(it.place || it.scene_label || "이름 없음")}</span>${certaintyBadge(a.certainty)}</div>
        ${a.description ? `<p class="issue-desc">${esc(a.description)}</p>` : ""}
        ${attrsList(a)}
        ${sourceBox(a.source_text)}
        ${metaRow(it, ctx, it.place && it.scene_label ? it.scene_label : "")}
      </div>`;
    })
    .join("")}</div>`;
}

// 사건: 요약 + 등장 인물(이름 치환) + 원인 → 결과 흐름. attrs 가 없는(0005 이전) 행은 제목·단계만.
function eventsHtml(data, ctx) {
  const items = [...(data.items || [])].sort(byChapterThenOrder);
  if (!items.length) return emptyHtml("events", ctx);
  return `<div class="issue-list">${items
    .map((it) => {
      const a = it.attrs || {};
      const actor = a.main_actor_character_id ? nameOf(ctx, a.main_actor_character_id) : "";
      const participants = (a.participant_character_ids || []).map((id) => nameOf(ctx, id));
      const people = [
        actor ? `<span class="wv-trait-chip canon-chip-strong" title="주요 인물">${esc(actor)}</span>` : "",
        ...participants.filter((n) => n !== actor).map((n) => `<span class="wv-trait-chip">${esc(n)}</span>`),
      ].join("");
      const flow =
        a.cause || a.result
          ? `<div class="canon-flow">
              <div class="canon-flow-step"><span class="canon-flow-tag">원인</span><span>${esc(a.cause || "정보 없음")}</span></div>
              <span class="canon-flow-arrow" aria-hidden="true">→</span>
              <div class="canon-flow-step"><span class="canon-flow-tag">결과</span><span>${esc(a.result || "정보 없음")}</span></div>
            </div>`
          : "";
      return `
      <div class="issue-card${cardClass(it, ctx)}">
        <div class="issue-header">
          <span class="dot dot-red"></span>
          <span>${it.order_index != null ? `${esc(String(it.order_index))}. ` : ""}${esc(it.label || "제목 없음")}</span>
          ${certaintyBadge(a.certainty)}
        </div>
        ${a.summary ? `<p class="issue-desc">${esc(a.summary)}</p>` : ""}
        ${it.stage ? `<div class="wv-meta-row">단계: ${esc(it.stage)}</div>` : ""}
        ${people ? `<div class="wv-chip-row"><span class="wv-chip-label">등장 인물</span>${people}</div>` : ""}
        ${flow}
        ${attrsList(a)}
        ${sourceBox(a.source_text)}
        ${metaRow(it, ctx)}
      </div>`;
    })
    .join("")}</div>`;
}

// 인물: 관계도(SVG 원형 배치, 간선 = 감정 색, 노드 클릭 → 카드로 스크롤) + 인물 카드
function charactersHtml(data, ctx) {
  const rows = [...(data.nodes || [])].sort(byKeyThenVersion);
  const edges = data.edges || [];
  if (!rows.length && !edges.length) return emptyHtml("characters", ctx);

  // 관계도 노드는 키당 하나(가장 높은 버전). chapter=N 에서 엣지가 다른 회차 인물을 가리키면 흐린 노드로 보탠다.
  const graphNodes = new Map();
  for (const n of rows) {
    const prev = graphNodes.get(n.id);
    if (!prev || (n.version ?? 0) >= (prev.version ?? 0)) graphNodes.set(n.id, n);
  }
  const names = { ...(ctx.names || {}), ...Object.fromEntries(rows.map((n) => [n.id, n.name])) };
  for (const e of edges) {
    for (const id of [e.from, e.to]) {
      if (id && !graphNodes.has(id)) graphNodes.set(id, { id, name: names[id] || id, ghost: true });
    }
  }
  const gNodes = [...graphNodes.values()];

  const W = 640, H = 420, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 70;
  const pos = {};
  gNodes.forEach((n, i) => {
    const ang = (2 * Math.PI * i) / gNodes.length - Math.PI / 2;
    pos[n.id] = gNodes.length === 1 ? { x: cx, y: cy } : { x: cx + R * Math.cos(ang), y: cy + R * Math.sin(ang) };
  });
  const lines = edges
    .map((e) => {
      const a = pos[e.from], b = pos[e.to];
      if (!a || !b) return "";
      const color = sentimentToColor(e.attrs?.sentiment);
      // A→B 와 B→A 가 겹치지 않게 진행 방향의 오른쪽으로 조금 비켜 그린다
      const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const ox = (-(b.y - a.y) / len) * 5, oy = ((b.x - a.x) / len) * 5;
      const mx = (a.x + b.x) / 2 + ox * 3, my = (a.y + b.y) / 2 + oy * 3;
      return `<g class="${supersededClass(e).trim()}"><title>${esc(e.attrs?.description || e.relation || "")}</title>
              <line x1="${a.x + ox}" y1="${a.y + oy}" x2="${b.x + ox}" y2="${b.y + oy}" class="canon-edge" style="stroke:${color}"/>
              <text x="${mx}" y="${my + 4}" class="canon-edge-label">${esc(e.relation || e.attrs?.relationship_type || "")}</text></g>`;
    })
    .join("");
  const circles = gNodes
    .map((n) => {
      const p = pos[n.id];
      const color = stringToPaletteColor(n.id);
      return `<g class="canon-node-g${n.ghost ? " canon-node-ghost" : ""}" ${n.ghost ? "" : `data-scroll-to="canon-char-${esc(n.id)}"`}>
        <title>${esc(n.ghost ? `${n.name} (다른 회차 인물)` : `${n.name} — 눌러서 카드 보기`)}</title>
        <circle cx="${p.x}" cy="${p.y}" r="34" class="canon-node" style="stroke:${color};fill:color-mix(in srgb, ${color} 14%, var(--card))"/>
        <text x="${p.x}" y="${p.y - 2}" class="canon-node-name">${esc(shortName(n.name))}</text>
        <text x="${p.x}" y="${p.y + 14}" class="canon-node-group">${esc(n.group || "")}</text>
      </g>`;
    })
    .join("");
  const usedSentiments = [...new Set(edges.map((e) => String(e.attrs?.sentiment || "neutral").toLowerCase()))];
  const legend = edges.length
    ? `<div class="canon-legend">${usedSentiments
        .map((s) => `<span><i style="background:${sentimentToColor(s)}"></i>${esc(sentimentToKorean(s))}</span>`)
        .join("")}</div>`
    : "";
  const graph = `<svg class="canon-graph" viewBox="0 0 ${W} ${H}" role="img" aria-label="인물 관계도">${lines}${circles}</svg>${legend}`;

  const seenCardIds = new Set();
  const cards = rows
    .map((n) => {
      const a = n.attrs || {};
      // traits: 문자열 배열(옛 캐논) 또는 {trait, trait_type, certainty} 객체 배열(0005 이후) 둘 다 받는다
      const traits = (a.traits || [])
        .map((t) => (typeof t === "string" ? { trait: t } : t))
        .filter((t) => t && t.trait)
        .map(
          (t) =>
            `<span class="wv-trait-chip" title="${esc([t.trait_type, t.certainty ? `신뢰도 ${certaintyToStars(t.certainty)}` : ""].filter(Boolean).join(" · "))}">${esc(t.trait)}</span>`
        )
        .join("");
      const aliases = (a.aliases || []).join(", ");
      const rels = edges
        .filter((e) => e.from === n.id || e.to === n.id)
        .map((e) => {
          const other = e.from === n.id ? e.to : e.from;
          const otherName = names[other] || other;
          const color = sentimentToColor(e.attrs?.sentiment);
          const dir = e.from === n.id ? "→" : "←";
          return `
            <div class="relationship-item${supersededClass(e)}" title="${esc(e.attrs?.description || "")}">
              <span class="relationship-avatar" style="${avatarStyle(other)}">${esc(avatarInitial(otherName))}</span>
              <span class="relationship-name">${dir} ${esc(otherName)}</span>
              <span class="relationship-type">${esc(e.relation || e.attrs?.relationship_type || "관계")}</span>
              <span class="relationship-sentiment" style="color:${color}">
                <span class="relationship-sentiment-dot" style="background:${color}"></span>${esc(sentimentToKorean(e.attrs?.sentiment))}
              </span>
            </div>`;
        })
        .join("");
      // 같은 인물의 여러 버전 카드 중 첫 장에만 스크롤 대상 id 를 단다
      const anchor = seenCardIds.has(n.id) ? "" : `id="canon-char-${esc(n.id)}"`;
      seenCardIds.add(n.id);
      return `
      <div class="character-card${cardClass(n, ctx)}" ${anchor}>
        <div class="character-card-top">
          <span class="character-avatar" style="${avatarStyle(n.id)}">${esc(avatarInitial(n.name))}</span>
          <div class="character-card-titles">
            <div class="character-name-row">
              <span class="character-name">${esc(n.name || "이름 없음")}</span>
              ${certaintyBadge(a.certainty)}
            </div>
            ${aliases ? `<div class="wv-aliases">${esc(aliases)}</div>` : ""}
            ${n.group ? `<div class="wv-aliases">${esc(n.group)}</div>` : ""}
          </div>
        </div>
        ${a.description ? `<p class="issue-desc">${esc(a.description)}</p>` : ""}
        ${traits ? `<div class="wv-chip-row"><span class="wv-chip-label">특징</span>${traits}</div>` : ""}
        ${
          rels
            ? `<div class="relationship-block"><span class="wv-chip-label">관계 인물</span><div class="relationship-list">${rels}</div></div>`
            : ""
        }
        ${attrsList(a)}
        ${sourceBox(a.source_text)}
        ${metaRow(n, ctx)}
      </div>`;
    })
    .join("");

  // 이 회차에 인물 행은 없고 관계만 바뀐 경우
  const relOnly = !rows.length
    ? `<p class="visual-placeholder">이 회차에서 바뀐 인물 정보는 없고, 관계만 바뀌었어요.</p>`
    : "";
  return `${graph}${relOnly}<div class="character-grid">${cards}</div>`;
}

function foreshadowingHtml(data, ctx) {
  // 회차별 시각화 원본(LLM 포맷)에 복선이 없다 — 복선은 "전체"에서만 트리로 (D23)
  if (ctx.mode !== "all") return `<p class="visual-placeholder">복선은 "전체"에서 봅니다. 회차를 이어 설치·회수를 트리로 보여줘요.</p>`;
  const items = data.items || [];
  if (!items.length) return emptyHtml("foreshadowing", ctx);
  const byParent = {};
  items.forEach((it) => {
    const k = it.parent_id || "__root__";
    (byParent[k] = byParent[k] || []).push(it);
  });
  const node = (it) => {
    const kids = byParent[it.id] || [];
    return `<li>
      <span class="canon-fnode canon-fnode--${esc(it.kind)}" title="${esc(it.entity_key || "")}">
        <b>${it.kind === "setup" ? "설치" : "회수"}</b> ${esc(it.label)}
        <small>${it.source_chapter != null ? it.source_chapter + "화" : ""}</small>
      </span>
      ${kids.length ? `<ul>${kids.map(node).join("")}</ul>` : ""}
    </li>`;
  };
  // 부모가 목록에 없는 항목도 뿌리로 보여준다
  const ids = new Set(items.map((it) => it.id));
  const roots = items.filter((it) => !it.parent_id || !ids.has(it.parent_id));
  return `<ul class="canon-ftree">${roots.map(node).join("")}</ul>`;
}

const RENDERERS = {
  worldview: worldviewHtml,
  characters: charactersHtml,
  timeline: timelineHtml,
  spaces: spacesHtml,
  events: eventsHtml,
  foreshadowing: foreshadowingHtml,
};

// 어느 데이터를 그렸는지 상단 한 줄 (D22)
function sourceBanner(ctx) {
  if (ctx.mode === "delta")
    return `<div class="canon-source-banner is-delta"><b>저장 전 추출 결과</b> · ${ctx.chapterNo}화 — 검토·저장하면 캐논에 반영돼요</div>`;
  if (ctx.mode === "chapter")
    return `<div class="canon-source-banner"><b>캐논 반영분</b> · ${ctx.chapterNo}화가 캐논에 넣은 항목</div>`;
  return `<div class="canon-source-banner"><b>현재 캐논</b> · 저장된 회차 전체</div>`;
}

/**
 * 캐논 view 응답(또는 deltaToCanonViews 의 한 view) → HTML
 * @param ctx {mode: "all"|"chapter"|"delta", chapterNo?, names?: {entity_key: 인물 이름}, prevSourceOf?: {entity_key: 화}}
 */
export function renderCanonView(view, data, ctx = { mode: "all" }) {
  const render = RENDERERS[view];
  const body = render ? render(data || {}, ctx) : `<p class="visual-placeholder">준비 중인 항목이에요.</p>`;
  // 회차별 복선은 데이터 없이 안내문만 — 출처 줄을 달지 않는다
  if (view === "foreshadowing" && ctx.mode !== "all") return body;
  return sourceBanner(ctx) + body;
}

/** 인물 view(nodes) 여러 개 → entity_key → 이름 맵. 뒤에 준 것이 우선. */
export function characterNames(...views) {
  const out = {};
  for (const v of views) for (const n of v?.nodes || []) if (n.id && n.name) out[n.id] = n.name;
  return out;
}

/** 대체된 버전의 출처 회차를 찾을 필요가 있나 (chapter=N 응답에 version > 1 인 행이 있으면) */
export function hasReplacedRows(data) {
  return [...(data?.items || []), ...(data?.nodes || []), ...(data?.edges || [])].some((it) => it.version > 1);
}

/** N-1화 시점 캐논 응답 → entity_key → source_chapter */
export function sourceChapterMap(data) {
  const out = {};
  for (const it of [...(data?.items || []), ...(data?.nodes || []), ...(data?.edges || [])])
    if (it.entity_key) out[it.entity_key] = it.source_chapter;
  return out;
}

/**
 * 저장 전 회차의 result.canon_delta(1차 탭이 delta-view.js 로 읽는 그 입력) → 캐논 6뷰 응답 모양.
 * delta 항목도 entity_key·attrs 를 가지므로 같은 렌더러로 그린다. 버전 메타는 없다.
 */
export function deltaToCanonViews(canonDelta) {
  const d = canonDelta || {};
  return {
    worldview: { items: d.worldview || [] },
    characters: {
      nodes: (d.characters || []).map((c) => ({ ...c, id: c.entity_key, group: c.group_name })),
      edges: (d.relations || []).map((r) => ({ ...r, from: r.from_char, to: r.to_char })),
    },
    timeline: { items: d.timeline || [] },
    spaces: { items: d.spaces || [] },
    events: { items: d.events || [] },
    foreshadowing: {
      items: (d.foreshadowing || []).map((f) => ({ ...f, id: f.entity_key, parent_id: f.parent_key || null })),
    },
  };
}

/** 관계도 노드 클릭 → 해당 인물 카드로 스크롤. 컨테이너에 한 번만 건다. */
export function bindCanonView(container) {
  container.addEventListener("click", (ev) => {
    const target = ev.target.closest?.("[data-scroll-to]");
    if (!target) return;
    const card = document.getElementById(target.dataset.scrollTo);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("canon-flash");
    void card.offsetWidth; // 애니메이션 다시 시작
    card.classList.add("canon-flash");
  });
}

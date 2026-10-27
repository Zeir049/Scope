"""캐논 비즈니스 로직: 스냅샷 구성 + append-only 병합.

CLAUDE.md 불변원칙 2: 덮어쓰지 않는다. 설정이 바뀌면 옛 행 is_current=false +
새 행 version+1 INSERT. 같은 내용이면 멱등(아무것도 안 함).
SPEC 한 곳으로 7개 canon 테이블을 모두 제네릭 처리한다.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.models import (
    CanonCharacter,
    CanonEvent,
    CanonForeshadowing,
    CanonRelation,
    CanonSpace,
    CanonTimeline,
    CanonWorldview,
)
from app.models.base import Base
from app.pipeline.interface import CanonSnapshot
from app.repository.canon_repo import CanonRepository

logger = logging.getLogger(__name__)

# (canon_delta 필드명, 모델, 내용 컬럼들) — 스냅샷/병합 양쪽이 공유.
# attrs 는 복선을 뺀 6종에 있다(0005). 병합 비교는 normalize_for_compare 를 거친다.
CanonSpec = tuple[str, type[Base], list[str]]
CANON_SPECS: list[CanonSpec] = [
    ("worldview", CanonWorldview, ["item", "detail", "attrs"]),
    ("characters", CanonCharacter, ["name", "group_name", "attrs"]),
    ("relations", CanonRelation, ["from_char", "to_char", "relation", "attrs"]),
    ("timeline", CanonTimeline, ["scene_label", "order_index", "time_value", "attrs"]),
    ("spaces", CanonSpace, ["scene_label", "place", "attrs"]),
    ("events", CanonEvent, ["label", "stage", "order_index", "attrs"]),
    ("foreshadowing", CanonForeshadowing, ["label", "parent_key", "kind"]),
]

# attrs 안에서 버전업 판정에 넣지 않는 키. 출처 인용과 확신도는 같은 설정을 다시
# 추출할 때마다 흔들리는 값이라, 이것만 달라진 항목에 새 버전을 쌓으면 이력이 잡음으로
# 찬다. (중첩된 traits 의 certainty 도 같은 이유로 뺀다.)
COMPARE_IGNORED_ATTR_KEYS: frozenset[str] = frozenset({"source_text", "certainty"})


def _strip_ignored(value: Any) -> Any:
    """dict/list 를 재귀로 내려가며 비교 제외 키를 지운다. 그 외 값은 그대로."""
    if isinstance(value, dict):
        return {
            k: _strip_ignored(v)
            for k, v in value.items()
            if k not in COMPARE_IGNORED_ATTR_KEYS
        }
    if isinstance(value, list):
        return [_strip_ignored(v) for v in value]
    return value


def normalize_for_compare(content: dict) -> dict:
    """병합 비교 전용 정규화 — '의미 있는 내용'만 남긴다.

    - attrs 에서 source_text·certainty 를 (중첩 포함) 뺀다.
    - 그렇게 비워진 attrs 와 None 은 같은 것으로 본다({} → None).
    - 비교에만 쓴다. 저장되는 값은 원본 그대로(출처 인용은 보관한다).
    """
    out = dict(content)
    if "attrs" in out:
        attrs = _strip_ignored(out["attrs"]) if isinstance(out["attrs"], dict) else out["attrs"]
        out["attrs"] = attrs or None
    return out


class CanonService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = CanonRepository(session)

    async def has_contribution(self, project_id: uuid.UUID, source_chapter: int) -> bool:
        """이 회차가 캐논에 넣은 행이 하나라도 있는가 (is_current 무관, 철회 행 포함)."""
        return await self.repo.has_contribution(
            [model for _, model, _ in CANON_SPECS], project_id, source_chapter
        )

    async def build_snapshot(
        self, project_id: uuid.UUID, at_chapter: int | None = None
    ) -> CanonSnapshot:
        """캐논을 파이프라인 입력 형태로 구성.

        at_chapter=None → 현재 캐논(is_current=true). 추출(extract)이 쓴다.
        at_chapter=N    → N화 시점 캐논(list_at_chapter). 검수는 N-1 을 넘긴다(D6).
        """
        data: dict[str, list[dict]] = {}
        max_chapter = 0
        for field, model, content_fields in CANON_SPECS:
            if at_chapter is None:
                rows = await self.repo.list_current(model, project_id)
            else:
                rows = await self.repo.list_at_chapter(model, project_id, at_chapter)
            entries = []
            for r in rows:
                entry = {
                    "id": str(r.id),
                    "entity_key": r.entity_key,
                    "source_chapter": r.source_chapter,
                    "version": r.version,
                }
                for f in content_fields:
                    entry[f] = getattr(r, f)
                entries.append(entry)
                max_chapter = max(max_chapter, r.source_chapter)
            data[field] = entries
        return CanonSnapshot(
            project_id=str(project_id),
            up_to_chapter=max_chapter if at_chapter is None else at_chapter,
            **data
        )

    # ── 자료정리 6탭 조회 (계약서 4장) ─────────────────────────
    VIEWS = {
        "worldview",
        "characters",
        "timeline",
        "spaces",
        "events",
        "foreshadowing",
    }

    @staticmethod
    def _meta(r: Base) -> dict:
        """모든 탭 항목이 공통으로 갖는 버전 정보.

        superseded_at_chapter 는 이 버전이 몇 화에서 대체/철회됐는지(현재 버전이면 None).
        chapter=N 조회가 대체된 버전도 돌려주므로 프론트가 이걸로 구분한다.
        """
        return {
            "entity_key": r.entity_key,  # type: ignore[attr-defined]
            "source_chapter": r.source_chapter,  # type: ignore[attr-defined]
            "version": r.version,  # type: ignore[attr-defined]
            "is_current": r.is_current,  # type: ignore[attr-defined]
            "superseded_at_chapter": r.superseded_at_chapter,  # type: ignore[attr-defined]
        }

    async def get_view(
        self,
        project_id: uuid.UUID,
        view: str,
        at_chapter: int | None = None,
        chapter: int | None = None,
    ) -> dict:
        """탭 조회.

        at_chapter=None, chapter=None → 현재 캐논(is_current).
        at_chapter=N → N화 시점 캐논(그때 유효했던 버전들, 항목당 1행).
        chapter=N    → N화가 캐논에 넣은 행 전부(이후 대체된 버전 포함) — 회차별 시각화용.
        둘을 함께 주면 400.
        """
        if view not in self.VIEWS:
            raise DomainError(
                f"알 수 없는 view: {view}. 가능: {', '.join(sorted(self.VIEWS))}"
            )
        if at_chapter is not None and chapter is not None:
            raise DomainError("at_chapter와 chapter는 함께 지정할 수 없습니다.")
        if at_chapter is not None and at_chapter < 0:
            raise DomainError("at_chapter는 0 이상이어야 합니다.")
        if chapter is not None and chapter < 1:
            raise DomainError("chapter는 1 이상이어야 합니다.")

        async def rows_of(model: type[Base]) -> list:
            if chapter is not None:
                return await self.repo.list_by_source(model, project_id, chapter)
            if at_chapter is not None:
                return await self.repo.list_at_chapter(model, project_id, at_chapter)
            return await self.repo.list_current(model, project_id)

        meta = self._meta

        if view == "characters":
            # 인물 탭만 그래프(노드+엣지). node id = entity_key (엣지가 이걸로 연결).
            chars = await rows_of(CanonCharacter)
            rels = await rows_of(CanonRelation)
            nodes = [
                {"id": c.entity_key, "name": c.name, "group": c.group_name, "attrs": c.attrs}
                | meta(c)
                for c in chars
            ]
            edges = [
                {"from": r.from_char, "to": r.to_char, "relation": r.relation, "attrs": r.attrs}
                | meta(r)
                for r in rels
            ]
            return {"view": view, "nodes": nodes, "edges": edges}

        if view == "worldview":
            rows = await rows_of(CanonWorldview)
            items = [
                {"id": str(r.id), "item": r.item, "detail": r.detail, "attrs": r.attrs} | meta(r)
                for r in rows
            ]
        elif view == "timeline":
            rows = await rows_of(CanonTimeline)
            rows.sort(key=lambda r: r.order_index)
            items = [
                {
                    "id": str(r.id),
                    "scene_label": r.scene_label,
                    "order_index": r.order_index,
                    "time_value": r.time_value,
                    "attrs": r.attrs,
                }
                | meta(r)
                for r in rows
            ]
        elif view == "spaces":
            rows = await rows_of(CanonSpace)
            items = [
                {
                    "id": str(r.id),
                    "scene_label": r.scene_label,
                    "place": r.place,
                    "attrs": r.attrs,
                }
                | meta(r)
                for r in rows
            ]
        elif view == "events":
            rows = await rows_of(CanonEvent)
            rows.sort(key=lambda r: r.order_index)
            items = [
                {
                    "id": str(r.id),
                    "label": r.label,
                    "stage": r.stage,
                    "order_index": r.order_index,
                    "attrs": r.attrs,
                }
                | meta(r)
                for r in rows
            ]
        else:  # foreshadowing — 트리(parent_id로 구성). id = entity_key. attrs 없음(원본 포맷에 없다).
            rows = await rows_of(CanonForeshadowing)
            items = [
                {"id": r.entity_key, "label": r.label, "parent_id": r.parent_key, "kind": r.kind}
                | meta(r)
                for r in rows
            ]
        return {"view": view, "items": items}

    async def merge_delta(
        self, project_id: uuid.UUID, canon_delta: dict, source_chapter: int
    ) -> dict[str, int]:
        """canon_delta를 캐논에 병합. 호출자(save)의 트랜잭션 안에서 실행됨.

        병합 후 '유령 정리'까지 수행한다: 이 회차가 출처인 현재 항목 중 이번
        델타에 없는 것은 기여가 철회된 것이므로 폐기(retired)하고, 다른 회차가
        만든 직전 버전이 있으면 그걸 복원(restored)한다 — 수정 원고 재분석 시
        삭제된 설정이 캐논에 남는 문제 방지. append-only 원칙 유지(마킹만, DELETE 없음).
        """
        stats = {"inserted": 0, "versioned": 0, "unchanged": 0, "retired": 0, "restored": 0}
        for field, model, content_fields in CANON_SPECS:
            delta_items = canon_delta.get(field, []) or []
            for item in delta_items:
                result = await self._merge_item(
                    model, content_fields, project_id, item, source_chapter
                )
                stats[result] += 1
            await self._retire_stale(
                model, project_id, source_chapter,
                {item["entity_key"] for item in delta_items}, stats,
            )
        logger.info("canon merged for project=%s ch=%s: %s", project_id, source_chapter, stats)
        return stats

    async def _retire_stale(
        self,
        model: type[Base],
        project_id: uuid.UUID,
        source_chapter: int,
        delta_keys: set[str],
        stats: dict[str, int],
    ) -> None:
        """이 회차 출처의 현재 항목 중 델타에 없는 것을 철회 (+ 직전 버전 복원).

        - 다른 회차가 출처인 항목은 절대 건드리지 않는다 (source_chapter 조건).
        - 철회 = is_current=false 마킹 (superseded_by 없음 — 대체가 아니라 회수).
        - 이 회차가 수정하기 전 다른 회차의 버전이 있으면 그걸 현재로 복원한다.
        - 재저장 멱등: 이미 철회된 항목은 current가 아니므로 다시 잡히지 않는다.
        """
        for row in await self.repo.list_current_by_source(model, project_id, source_chapter):
            if row.entity_key in delta_keys:
                continue
            row.is_current = False
            row.superseded_at_chapter = source_chapter
            await self.s.flush()  # 부분 유니크(current 1개) 슬롯을 비운 뒤 복원
            stats["retired"] += 1

            prev = await self.repo.get_latest_excluding_source(
                model, project_id, row.entity_key, source_chapter
            )
            if prev is not None:
                prev.is_current = True
                prev.superseded_at_chapter = None
                prev.superseded_by = None
                await self.s.flush()
                stats["restored"] += 1

    async def _merge_item(
        self,
        model: type[Base],
        content_fields: list[str],
        project_id: uuid.UUID,
        item: dict,
        source_chapter: int,
    ) -> str:
        entity_key = item["entity_key"]
        new_content = {f: item.get(f) for f in content_fields}
        current = await self.repo.get_current(model, project_id, entity_key)

        if current is None:
            # 신규이거나, 철회(retired)됐던 항목의 재추가 — 버전은 이력에 이어 매긴다
            max_version = await self.repo.get_max_version(model, project_id, entity_key)
            await self.repo.insert_version(
                model, project_id, entity_key, new_content,
                version=max_version + 1, source_chapter=source_chapter,
            )
            return "inserted"

        old_content = {f: getattr(current, f) for f in content_fields}
        if normalize_for_compare(old_content) == normalize_for_compare(new_content):
            return "unchanged"  # 멱등: 의미 있는 내용이 같으면 새 버전 안 만듦

        # append-only: 옛 행을 먼저 is_current=false 로 내려 부분 유니크 슬롯을 비운 뒤
        # (flush로 UPDATE를 INSERT보다 먼저 보냄) 새 버전을 INSERT 한다.
        current.is_current = False
        current.superseded_at_chapter = source_chapter
        await self.s.flush()

        new_row = await self.repo.insert_version(
            model, project_id, entity_key, new_content,
            version=current.version + 1, source_chapter=source_chapter,
        )
        current.superseded_by = new_row.id
        return "versioned"

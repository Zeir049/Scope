"""시연용 리플레이 자료 생성 (PIPELINE_MODE=replay 가 읽는 app/pipeline/replay_data/).

AI 파트 실행 결과를 1·2·3화로 나눠, 회차마다 AI 서버가 돌려줬을 응답을 미리 만들어 둔다.

입력 (AI 파트 산출물 — 저장소 밖에 있으므로 경로를 인자로 받는다)
  --story     weave/ers_all_pairs_standalone/story   인셉션 각본 1회차 분석 결과(ep_global.json, 전역 ID)
  --ers-eval  ers_eval                                심은 모순(contradictions/planted.json)과
                                                      그 검수 답(review/detect_session_rules.json)

출력 (--out, 기본 app/pipeline/replay_data/)
  chapter_N.txt   업로드할 원문. 사건 요약을 순서대로 이어 쓴 글 + 심은 모순 사건 문장.
  chapter_N.json  {chapter_no, title, text_sha1, visual, contradictions}
                  visual        = /extract 응답(rich JSON, global ID, times[].expression 채움)
                  contradictions = /review 응답(ContradictionOut 목록)

나누는 기준
  - 사건·시간·장소: AI 파트 평가의 split3 과 같다(order 순 29개씩 — ers_eval/eval_ers.py).
  - 세계관 규칙·인물 특징·관계: 원본에 회차 정보가 없어(전부 1회차) 처음 드러나는 장면의
    회차를 사람이 정했다(아래 *_CHAPTER 표). 특징은 누적이라 뒤 회차에서 인물 새 버전이 쌓인다.
  - 복선: AI 결과에 없으므로 만들지 않는다.

변환 규칙은 ai_server/server/scope_bridge.py 를 따른다(to_visual·describe_time·to_contradictions).
다만 모순 인용은 원문이 요약체라 관련 사건의 source_text(각본 대사) 대신 summary 를 쓰고,
회차 번호는 이 분할 기준으로 다시 매긴다.

사용법:
  python scripts/build_replay_data.py --story <...>/story --ers-eval <...>/ers_eval
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

N_CHAPTERS = 3
OUT_DEFAULT = Path(__file__).resolve().parent.parent / "app" / "pipeline" / "replay_data"

CHAPTER_TITLES = {1: "의뢰", 2: "설계와 하강", 3: "림보"}

# 세계관 규칙 → 처음 설명되는 회차 (없으면 1화)
RULE_CHAPTER = {
    **{f"RULE_{n:03d}": 2 for n in (8, 11, 12, 13, 15, 17, 18, 20, 21, 22, 23, 24, 25)},
    **{f"RULE_{n:03d}": 3 for n in (16, 26)},
}
# (인물, traits 순번) → 처음 드러나는 회차 (없으면 그 인물이 처음 나온 회차)
TRAIT_CHAPTER = {
    ("CHAR_001", 3): 2, ("CHAR_001", 4): 3, ("CHAR_001", 6): 2, ("CHAR_001", 7): 2,
    ("CHAR_002", 0): 2, ("CHAR_002", 2): 3, ("CHAR_002", 3): 3,
    ("CHAR_003", 0): 2, ("CHAR_003", 1): 2, ("CHAR_003", 2): 2,
    ("CHAR_004", 1): 2, ("CHAR_004", 2): 3, ("CHAR_004", 3): 2,
    ("CHAR_010", 1): 2, ("CHAR_010", 2): 2,
}
# (인물, relationships 순번) → 처음 드러나는 회차 (없으면 그 인물이 처음 나온 회차)
RELATION_CHAPTER = {
    ("CHAR_001", 6): 2, ("CHAR_001", 7): 2, ("CHAR_001", 8): 2,
    ("CHAR_002", 1): 2,
    ("CHAR_003", 1): 2,
    ("CHAR_004", 0): 3, ("CHAR_004", 1): 2,
    ("CHAR_010", 0): 2,
}
# 시연에 쓸 심은 모순 (planted.json id). 검수에서 conflict 로 잡힌 것 중 회차당 4건.
PLANTED_IDS = ("P07", "P14", "P11", "P06", "P12", "P01", "P13", "P20")

# scope_bridge 와 같은 표
TYPE_MAP = {
    "setting": "setting", "character": "character", "time": "timeline",
    "location": "space", "causal": "event", "other": "event",
}
SEVERITY_CONFIDENCE = {"conflict": 0.9, "check_needed": 0.6}
TIME_GAPS = {
    1: "수초~수분", 2: "수십 분~수 시간", 3: "같은 날 다른 시간대", 4: "약 하루",
    5: "수일", 6: "수주~수개월", 7: "수년", 8: "아주 먼 시점",
}
TIMELINE_LABELS = {"flashback": "회상", "flashforward": "미래 장면", "parallel": "병행"}

# 검수 답에 섞인 평가용 내부 메모 — 화면에 보일 설명에서 뺀다.
#   (유형 목록에 object가 없어 other로 분류) : 평가 세트의 type 목록 사정
#   (order 84) / (order 84.5)                 : 심은 사건의 삽입 위치(소수점이면 심은 것이 드러남)
INTERNAL_NOTE = re.compile(r"\((?:유형 목록에[^()]*|order [\d.]+)\)")

# 몸통 계약에 없는, 전역 통합 단계가 붙인 내부 필드 — /extract 응답에는 없다
INTERNAL_KEYS = ("source_local_id", "source_submission", "source_submissions")


def describe_time(time: dict) -> str:
    """scope_bridge.describe_time 과 같은 규칙: time_info x축 → 사람이 읽는 표현."""
    info = time.get("time_info")
    gap = info[0] if isinstance(info, list) and info and isinstance(info[0], int) else None
    if gap == 0:
        text = "직전 사건과 같은 시점"
    elif gap in TIME_GAPS:
        text = f"직전 사건보다 {TIME_GAPS[gap]} {'전' if time.get('offset') == 0 else '후'}"
    else:
        text = "시점 불명"
    label = TIMELINE_LABELS.get(time.get("timeline_type") or "")
    return f"[{label}] {text}" if label else text


def strip_internal(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in INTERNAL_KEYS}


def sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?", "다")) else text + "."


def build(story: Path, ers_eval: Path, out: Path) -> None:
    ep = json.loads((story / "ep_global.json").read_text(encoding="utf-8"))
    planted_all = {
        p["id"]: p
        for p in json.loads((ers_eval / "contradictions" / "planted.json").read_text(encoding="utf-8"))
    }
    answers = json.loads((ers_eval / "review" / "detect_session_rules.json").read_text(encoding="utf-8"))

    # ── 사건 분할 (split3) ──
    ordered = sorted(ep["events"], key=lambda e: e["order"])
    size = -(-len(ordered) // N_CHAPTERS)
    chapter_of = {e["event_id"]: i // size + 1 for i, e in enumerate(ordered)}

    # ── 심은 모순 사건: 다음 전역 번호를 붙여 insert_after_order 뒤에 끼운다 ──
    last_no = max(int(e["event_id"].split("_")[1]) for e in ordered)
    planted = sorted((planted_all[i] for i in PLANTED_IDS), key=lambda p: p["insert_after_order"])
    plant_event_id: dict[str, str] = {}
    plants_after: dict[int, list[dict]] = {}
    for k, p in enumerate(planted, start=1):
        eid = f"EVENT_{last_no + k:03d}"
        plant_event_id[p["id"]] = eid
        ev = {
            "event_id": eid,
            "title": p["event"]["title"],
            "summary": p["event"]["summary"],
            "participant_character_ids": p["event"]["participant_character_ids"],
            "main_actor_character_id": p["event"]["main_actor_character_id"],
            "cause": p["event"].get("cause") or "",
            "result": p["event"].get("result") or "",
            "source_text": sentence(p["event"]["summary"]),
            "certainty": "explicit",
        }
        plants_after.setdefault(p["insert_after_order"], []).append(ev)
        anchor = next(e for e in ordered if e["order"] == p["insert_after_order"])
        chapter_of[eid] = chapter_of[anchor["event_id"]]

    events_by_id = {e["event_id"]: e for e in ordered}
    for evs in plants_after.values():
        for ev in evs:
            events_by_id[ev["event_id"]] = ev

    # 인물이 처음 나오는 회차 = 첫 등장 사건과 첫 참여 사건 중 빠른 쪽
    first_chapter: dict[str, int] = {}
    for c in ep["characters"]:
        cands = [chapter_of[c["first_appearance_event_id"]]] if c.get("first_appearance_event_id") in chapter_of else []
        cands += [chapter_of[e["event_id"]] for e in ordered if c["character_id"] in e["participant_character_ids"]]
        first_chapter[c["character_id"]] = min(cands)

    times_by_event = {t["event_id"]: t for t in ep["times"]}
    locs_by_event = {loc["event_id"]: loc for loc in ep["locations"]}

    out.mkdir(parents=True, exist_ok=True)
    for n in range(1, N_CHAPTERS + 1):
        # 이 회차 사건 순서 (심은 사건 포함). order 는 회차마다 1부터 다시 센다.
        seq: list[dict] = []
        for e in ordered:
            if chapter_of[e["event_id"]] != n:
                continue
            seq.append(e)
            seq.extend(plants_after.get(e["order"], []))

        # ── 원문: 사건 요약을 세 개씩 한 문단으로 ──
        sentences = [sentence(e["summary"]) for e in seq]
        paragraphs = [" ".join(sentences[i : i + 3]) for i in range(0, len(sentences), 3)]
        text = "\n\n".join(paragraphs) + "\n"

        events, times, locations = [], [], []
        for i, e in enumerate(seq, start=1):
            ev = strip_internal(e)
            ev["order"] = i
            events.append(ev)
            if e["event_id"] in times_by_event:
                t = strip_internal(times_by_event[e["event_id"]])
                t["expression"] = describe_time(t)
                times.append(t)
            if e["event_id"] in locs_by_event:
                locations.append(strip_internal(locs_by_event[e["event_id"]]))

        rules = [
            strip_internal(r) for r in ep["worldview_rules"] if RULE_CHAPTER.get(r["rule_id"], 1) == n
        ]

        # 인물: 이 회차에 나오거나(참여) 새 정보가 드러나는 인물. 특징·관계는 이 회차까지 누적.
        present = {cid for e in seq for cid in e["participant_character_ids"]}
        characters = []
        for c in ep["characters"]:
            cid = c["character_id"]
            if first_chapter[cid] > n:
                continue
            base = first_chapter[cid]
            new_info = any(
                TRAIT_CHAPTER.get((cid, i), base) == n for i in range(len(c.get("traits", [])))
            ) or any(
                RELATION_CHAPTER.get((cid, i), base) == n for i in range(len(c.get("relationships", [])))
            )
            if cid not in present and not new_info:
                continue
            ch = copy.deepcopy(strip_internal(c))
            ch["traits"] = [
                t for i, t in enumerate(c.get("traits", [])) if TRAIT_CHAPTER.get((cid, i), base) <= n
            ]
            ch["relationships"] = [
                r for i, r in enumerate(c.get("relationships", []))
                if RELATION_CHAPTER.get((cid, i), base) <= n
            ]
            characters.append(ch)

        visual = {
            "worldview_rules": rules,
            "characters": characters,
            "events": events,
            "times": times,
            "locations": locations,
        }

        contradictions = []
        for p in planted:
            eid = plant_event_id[p["id"]]
            if chapter_of[eid] != n:
                continue
            contradictions.extend(
                to_contradictions(p["id"], answers, eid, plant_event_id, events_by_id, chapter_of, text)
            )

        (out / f"chapter_{n}.txt").write_text(text, encoding="utf-8")
        payload = {
            "chapter_no": n,
            "title": CHAPTER_TITLES[n],
            # replay.text_fingerprint 와 같은 규칙(공백·줄바꿈 무시)
            "text_sha1": hashlib.sha1("".join(text.split()).encode("utf-8")).hexdigest(),
            "visual": visual,
            "contradictions": contradictions,
        }
        (out / f"chapter_{n}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(
            f"{n}화: 사건 {len(events)} · 규칙 {len(rules)} · 인물 {len(characters)} · "
            f"시간 {len(times)} · 장소 {len(locations)} · 모순 {len(contradictions)} · 원문 {len(text)}자"
        )


def to_contradictions(
    plant_id: str,
    answers: dict,
    event_id: str,
    plant_event_id: dict[str, str],
    events_by_id: dict[str, dict],
    chapter_of: dict[str, int],
    text: str,
) -> list[dict]:
    """검수 답(issues) → ContradictionOut dict. scope_bridge.to_contradictions 와 같은 모양."""
    raw = answers[f"PLANT_{plant_id}"]
    review = json.loads(raw) if isinstance(raw, str) else raw

    def rename(s: str) -> str:
        # 검수 입력에서 심은 사건은 PLANT_Pxx 로 불렸다 — 여기서 붙인 사건 ID로 바꾼다
        s = re.sub(r"PLANT_(P\d+)", lambda m: plant_event_id.get(m.group(1), m.group(0)), s)
        return INTERNAL_NOTE.sub("", s)

    quote = events_by_id[event_id]["source_text"]
    start = text.index(quote)
    span = {"start": start, "end": start + len(quote), "quote": quote}

    out = []
    for item in review.get("events") or []:
        for issue in item.get("issues") or []:
            related = events_by_id.get(issue.get("related_event_id") or "")
            explanation = rename((issue.get("description") or "").strip())
            evidence = [rename(e.strip()) for e in issue.get("evidence") or [] if isinstance(e, str) and e.strip()]
            if evidence:
                explanation += "\n근거: " + " / ".join(evidence)
            out.append(
                {
                    "span": span,
                    "conflict_ref": {
                        "chapter_no": chapter_of[related["event_id"]] if related else None,
                        "quote": sentence(related["summary"]) if related else None,
                    },
                    "type": TYPE_MAP.get(issue.get("type") or "", "event"),
                    "explanation": explanation,
                    "confidence": SEVERITY_CONFIDENCE.get(issue.get("severity") or "", 0.6),
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--story", type=Path, required=True, help="ep_global.json 이 있는 폴더")
    ap.add_argument("--ers-eval", type=Path, required=True, help="ers_eval 폴더")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    build(args.story, args.ers_eval, args.out)


if __name__ == "__main__":
    main()

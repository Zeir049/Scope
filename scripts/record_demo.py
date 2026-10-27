"""Glitch 시연 영상 자동 녹화 (replay 모드 서버, 127.0.0.1:8000, FIREBASE_MODE=fake).

흐름: 로그인 → 새 프로젝트 만들기 → 1화 자세히(업로드 → 1차 결과 → 수정하기 → 1화 시각화 5개 탭 →
      2차 검토) → 2·3화 넘기듯(업로드 → 1차 결과 → 2차 검토 → 모순 카드, 2화는 ✓/✕ 판정) → 전체 시각화 5개 탭 자세히.
결과: <출력 폴더>/glitch_demo.webm (약 2분 30초)
      --one-minute 면 1~2화만, 1화 시각화는 세계관 탭만, 동작 0.7배 → glitch_demo_1min.webm (1분 이내,
      서버는 glitch-app-replay-video-short)
      --short 면 모든 시간 0.25배 → glitch_demo_short.webm
      1280x720, 소리 없음

준비 (프로젝트 .venv 와 별도 가상환경 권장. 브라우저는 설치된 Chrome 을 쓴다):
  py -3.12 -m venv pwenv && pwenv\\Scripts\\pip install playwright httpx
  pwenv\\Scripts\\python -m playwright install ffmpeg
실행:
  1) 서버: PIPELINE_MODE=replay QUEUE_MODE=inline FIREBASE_MODE=fake 로 uvicorn,
     REPLAY_DELAY_SECONDS 는 3분판 1.5 / 1분판 0.5 (.claude/launch.json 의 glitch-app-replay-video[-short])
  2) pwenv\\Scripts\\python scripts\\record_demo.py <출력 폴더> [--short]
녹화는 시연 전용 계정(demo@glitch.local)으로 하고, 같은 이름의 이전 시연 프로젝트는 지운 뒤 화면에서 새로 만든다.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:8000"
DATA = Path(r"C:\glitch_integrated\app\pipeline\replay_data")
PROJECT_NAME = "인셉션"
# 시연 전용 빈 계정(FIREBASE_MODE=fake) — 사이드바에 테스트 프로젝트가 안 보이게
DEMO_ID_TOKEN = "fake:demo@glitch.local:Glitch 시연"
EDIT_TEXT = "추출자는 표적의 꿈속 금고에 들어가 무의식 깊은 곳의 비밀을 빼낸다."
W, H = 1280, 720

# 영상에 마우스가 안 찍히므로 가짜 커서 + 클릭 파동을 그린다
CURSOR_JS = """
(() => {
  const add = () => {
    if (document.getElementById('__cursor')) return;
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;' +
      'background:rgba(20,20,20,.55);border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.4);z-index:2147483647;' +
      'pointer-events:none;transition:transform .12s';
    document.body.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      c.style.transform = 'scale(.7)';
      const r = document.createElement('div');
      r.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;width:10px;height:10px;margin:-5px 0 0 -5px;` +
        'border-radius:50%;border:3px solid rgba(34,197,94,.9);z-index:2147483646;pointer-events:none;transition:all .45s ease-out';
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.width = r.style.height = '46px'; r.style.margin = '-23px 0 0 -23px'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 500);
    }, true);
    addEventListener('mouseup', () => { c.style.transform = ''; }, true);
  };
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
})();
"""


# 모든 대기·커서 이동·스크롤 시간에 곱한다. 3분판 1.0, 1분판(--short) SHORT_SCALE.
SCALE = 1.0
SHORT_SCALE = 0.25


def pause(s: float) -> None:
    time.sleep(s * SCALE)


def click(page: Page, locator, wait_after: float = 0.35) -> None:
    """커서를 부드럽게 옮긴 뒤 클릭."""
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y, steps=max(4, round(18 * SCALE)))
    pause(0.12)
    page.mouse.down()
    page.mouse.up()
    pause(wait_after)


def smooth_scroll(page: Page, dy: int, steps: int = 24, dt: float = 0.045) -> None:
    steps = max(4, round(steps * SCALE))  # 휠 이벤트 수도 배율만큼(짧은 모드에서 고정 비용이 크다)
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        pause(dt)


def scroll_top(page: Page) -> None:
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    pause(0.45)


def wait_status(page: Page, no: int, statuses: tuple[str, ...], timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        st = page.evaluate(
            """async ([no]) => {
                 const t = sessionStorage.getItem('glitch_backend_token');
                 const pid = window.__pid;
                 const r = await fetch(`/projects/${pid}/chapters/${no}/result`, {headers: {Authorization: 'Bearer ' + t}});
                 return (await r.json()).status;
               }""",
            [no],
        )
        if st in statuses:
            return
        pause(0.2)
    raise TimeoutError(f"{no}화가 {statuses} 상태가 되지 않음")


def delete_old_projects() -> None:
    """이전 녹화에서 만든 같은 이름의 프로젝트를 지운다(프로젝트는 화면에서 새로 만든다)."""
    c = httpx.Client(base_url=BASE, timeout=30)
    tok = c.post("/auth/firebase", json={"id_token": DEMO_ID_TOKEN}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for p in c.get("/projects", params={"page": 1, "page_size": 50}, headers=h).json()["items"]:
        if p["name"] == PROJECT_NAME:
            c.delete(f"/projects/{p['id']}", headers=h)


def clear_tray(page: Page) -> None:
    """끝난 작업 카드를 닫는다(작업 창에 카드가 쌓여 화면을 가리지 않게)."""
    page.evaluate("document.querySelectorAll('.task-card-close').forEach(b => b.click())")
    pause(0.2)


def collapse_tray(page: Page) -> None:
    """완료 카드를 보여준 뒤 작업 창을 접는다(내용 오른쪽을 가리지 않게). 새 작업이 오면 다시 펼쳐진다."""
    pause(0.8)
    page.evaluate("document.querySelector('.task-tray:not(.collapsed) .task-tray-toggle')?.click()")
    pause(0.3)


def upload_and_extract(page: Page, no: int) -> None:
    clear_tray(page)
    page.set_input_files("#source-file", str(DATA / f"chapter_{no}.txt"))
    pause(0.9)
    click(page, page.locator("#analyze-btn"))
    wait_status(page, no, ("extracted",))
    page.wait_for_function("location.hash === '#result'", timeout=15000)
    page.locator("#tab-extract .extract-item").first.wait_for(timeout=15000)
    collapse_tray(page)


def show_extract(page: Page, detail: bool) -> None:
    """1차 분석 결과: 통계 카드 → 항목 목록을 훑는다. detail=False 면 짧게 넘긴다."""
    if detail:
        pause(2.0)
        smooth_scroll(page, 460, steps=30)
        pause(1.5)
        smooth_scroll(page, 380, steps=30)
        pause(1.2)
    else:
        pause(1.2)
        smooth_scroll(page, 360, steps=20)
        pause(0.8)
    scroll_top(page)


def review(page: Page, no: int) -> None:
    scroll_top(page)
    click(page, page.locator('.tab-btn[data-tab="report"]'), 0.7)
    click(page, page.locator("#report-review-btn"))
    wait_status(page, no, ("saved",))
    page.wait_for_function(
        "document.getElementById('report-review-btn').textContent.includes('다시 검토하기')", timeout=15000
    )
    collapse_tray(page)


def show_contradictions(page: Page, no: int) -> None:
    if no == 1:  # 첫 회차는 비교할 앞 내용이 없어 모순 0건
        pause(1.2)
        return
    if no == 2:
        judge_contradictions(page)
        return
    pause(1.0)
    smooth_scroll(page, 440, steps=24)
    pause(1.6)
    scroll_top(page)


def judge_contradictions(page: Page) -> None:
    """모순 카드 판정: 첫 카드는 ✓(모순 맞음), 둘째 카드는 ✕(무시). 누르면 바로 서버에 저장된다."""
    cards = page.locator("#issue-list .issue-card")
    pause(0.5)
    # 버튼이 카드 오른쪽 아래라 화면 맨 아래에 두면 접힌 작업 창 머리글에 가린다 — 가운데로 올린다
    center = "e => e.scrollIntoView({block: 'center', behavior: 'smooth'})"
    cards.nth(0).locator(".issue-confirm-btn").evaluate(center)
    pause(0.6)
    click(page, cards.nth(0).locator(".issue-confirm-btn"), 0.9)
    page.wait_for_function(
        "document.querySelector('#issue-list .issue-card').classList.contains('confirmed')", timeout=10000
    )
    cards.nth(1).locator(".issue-remove").evaluate(center)
    pause(0.6)
    click(page, cards.nth(1).locator(".issue-remove"), 0.9)
    page.wait_for_function(
        "document.querySelectorAll('#issue-list .issue-card')[1].classList.contains('dismissed')", timeout=10000
    )
    pause(0.8)
    scroll_top(page)


def next_round(page: Page) -> None:
    scroll_top(page)
    click(page, page.locator("#new-analysis-btn"), 0.8)
    page.wait_for_function("location.hash === '#analyze'", timeout=10000)
    pause(0.5)


def visual(page: Page, filter_label: str, category: str, hold: float, scroll: int = 0) -> None:
    bar = page.locator("#round-filter-bar-result")
    btn = bar.get_by_role("button", name=filter_label, exact=True)
    if "active" not in (btn.get_attribute("class") or ""):
        click(page, btn, 0.8)
    click(page, page.locator(f'.category-btn[data-category="{category}"]'), 0.85)
    page.wait_for_function(
        "!document.getElementById('visual-content').textContent.includes('불러오는 중')", timeout=10000
    )
    if scroll:
        smooth_scroll(page, scroll, steps=20, dt=0.05)
    pause(hold)
    scroll_top(page)


# 시각화 탭 (복선은 AI 결과에 없어 뺀다): (카테고리, 머무는 시간, 스크롤)
# 1화는 자세히(저장 전 추출 결과), 2·3화는 시각화 없이 넘기고, 마지막 "전체"를 가장 자세히 본다.
FIRST_CHAPTER_VISUALS = [
    ("worldview", 1.8, 320),
    ("character", 2.2, 560),   # 관계도 → 인물 카드
    ("time", 1.6, 380),
    ("space", 1.4, 320),
    ("event", 1.8, 420),
]
# --one-minute (1~2화, 1분 이내): 1화 시각화는 세계관(고친 문구)만, 전체는 5개 탭 모두.
# 시각화 탭 하나에 클릭·로딩·스크롤로 5초 남짓 드니 탭 수와 머무는 시간을 줄이고 동작은 0.7배.
ONE_MINUTE_SCALE = 0.7
ONE_MINUTE_FIRST_VISUALS = [
    ("worldview", 1.2, 200),
]
ONE_MINUTE_FINAL_VISUALS = [
    ("worldview", 1.0, 300),
    ("character", 1.4, 450),
    ("time", 0.6, 300),
    ("space", 0.5, 260),
    ("event", 0.9, 320),
]
# 인물 카드에는 "출처 3화 · 버전 3"이 보인다
FINAL_VISUALS = [
    ("worldview", 2.5, 700),
    ("character", 3.0, 900),
    ("time", 2.2, 700),
    ("space", 2.0, 600),
    ("event", 2.5, 800),
]


def show_visuals(page: Page, filter_label: str, plan: list[tuple[str, float, int]]) -> None:
    scroll_top(page)
    click(page, page.locator('.tab-btn[data-tab="visual"]'), 0.8)
    for category, hold, scroll in plan:
        visual(page, filter_label, category, hold, scroll)


def main() -> None:
    global SCALE
    ap = argparse.ArgumentParser(description="Glitch 시연 영상 녹화")
    ap.add_argument("out_dir", type=Path, nargs="?", default=Path(__file__).parent / "video")
    ap.add_argument("--short", action="store_true", help="모든 시간 0.25배 (서버 REPLAY_DELAY_SECONDS=0.5 권장)")
    ap.add_argument("--one-minute", action="store_true", help="1~2화만, 1분 이내 (서버 REPLAY_DELAY_SECONDS=0.5)")
    args = ap.parse_args()
    chapters = (1, 2) if args.one_minute else (1, 2, 3)
    first_visuals = ONE_MINUTE_FIRST_VISUALS if args.one_minute else FIRST_CHAPTER_VISUALS
    final_visuals = ONE_MINUTE_FINAL_VISUALS if args.one_minute else FINAL_VISUALS
    if args.short:
        SCALE = SHORT_SCALE
    elif args.one_minute:
        SCALE = ONE_MINUTE_SCALE
    out_dir: Path = args.out_dir

    delete_old_projects()
    tmp = out_dir / "_raw"
    shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(
            viewport={"width": W, "height": H}, record_video_dir=str(tmp),
            record_video_size={"width": W, "height": H}, locale="ko-KR",
        )
        ctx.add_init_script(CURSOR_JS)
        # 데모 로그인 버튼은 시드 계정 토큰을 보낸다 — 녹화에서는 시연 전용 계정으로 바꿔 보낸다
        ctx.route("**/auth/firebase", lambda route: route.continue_(
            post_data=json.dumps({"id_token": DEMO_ID_TOKEN}),
            headers={**route.request.headers, "content-type": "application/json"},
        ))
        page = ctx.new_page()
        t_rec = time.time()

        def mark(label: str) -> None:
            print(f"  {time.time() - t_rec:5.1f}s  {label}", flush=True)

        # ── 로그인 → 새 프로젝트 만들기 ──
        page.goto(f"{BASE}/?demo=1")
        pause(1.0)
        click(page, page.get_by_role("button", name="시작하기").first, 1.3)
        page.wait_for_function("location.hash === '#drive'", timeout=10000)
        click(page, page.locator("#new-project-btn"), 0.6)
        click(page, page.locator("#project-name-input"), 0.2)
        page.keyboard.type(PROJECT_NAME, delay=round(120 * SCALE))
        pause(0.6)
        click(page, page.locator("#project-name-confirm-btn"), 0.8)
        page.wait_for_function("location.hash === '#analyze'", timeout=10000)
        page.evaluate(
            """async (name) => {
                 const t = sessionStorage.getItem('glitch_backend_token');
                 const r = await fetch('/projects?page=1&page_size=50', {headers: {Authorization: 'Bearer ' + t}});
                 window.__pid = (await r.json()).items.find(p => p.name === name).id;
               }""",
            PROJECT_NAME,
        )
        pause(0.6)
        mark("새 프로젝트")

        # ── 회차마다: 업로드 → 1차 결과 → (1화: 수정하기) → 그 회차 시각화 전부 → 2차 → 모순 카드 ──
        for no in chapters:
            detail = no == 1  # 1화는 자세히, 2·3화는 넘기듯
            upload_and_extract(page, no)
            mark(f"{no}화 업로드·추출")
            if args.one_minute and not detail:
                pause(1.2)  # 1분판: 2화 1차 결과는 통계만 잠깐
            else:
                show_extract(page, detail and not args.one_minute)
            mark(f"{no}화 1차 결과")
            if detail:
                smooth_scroll(page, 260, steps=16)
                pause(0.8)
                item = page.locator("#tab-extract .extract-item").first
                click(page, item.locator(".extract-item-edit-toggle"), 0.7)
                content = item.locator(".extract-item-content")
                click(page, content, 0.4)
                page.keyboard.press("Control+A")
                page.keyboard.type(EDIT_TEXT, delay=max(8, round(40 * SCALE)))
                pause(1.0)
                click(page, item.locator(".extract-item-edit-toggle"), 1.6)
                mark("1화 수정하기")
                show_visuals(page, "1회차", first_visuals)   # 세계관 첫 카드에 방금 고친 문구
                mark("1화 시각화")
            review(page, no)
            mark(f"{no}화 2차 검토")
            show_contradictions(page, no)
            mark(f"{no}화 모순 카드")
            if no < chapters[-1]:
                next_round(page)

        # ── 마무리: 저장된 캐논 "전체" 시각화 전부 ──
        show_visuals(page, "전체", final_visuals)
        mark("전체 시각화")
        pause(0.5)

        video = page.video
        ctx.close()
        browser.close()
        raw = Path(video.path())
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "glitch_demo_1min" if args.one_minute else "glitch_demo_short" if args.short else "glitch_demo"
    out = out_dir / f"{name}.webm"
    shutil.move(str(raw), out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"saved {out}  ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()

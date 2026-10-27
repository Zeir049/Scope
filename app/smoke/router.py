# ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 삭제. 삭제법은 app/smoke/README.md 참조
"""스모크 라우터.

- GET  /smoke      : 자체 HTML 테스트 페이지(인증 불필요)
- POST /smoke/echo : 로그인 필요. 텍스트를 가짜 LLM(에코)에 보내고,
                     돌아온 텍스트가 입력과 같으면 'ok'(다르면 'mismatch')를 저장·반환.

내 프로젝트라면 어느 것이든(또는 프로젝트 없이) 동작한다 — 모든 유저·프로젝트 대상.
기존 컨벤션 준수: 인증은 get_current_user, 소유권은 assert_owned, 예외는 도메인 예외.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models import User
from app.repository.project_repo import ProjectRepository
from app.service.ownership import assert_owned
from app.smoke.llm import fake_llm_roundtrip
from app.smoke.model import SmokeCheck

router = APIRouter(tags=["smoke"])


class EchoIn(BaseModel):
    project_id: uuid.UUID | None = None
    text: str


@router.get("/smoke", response_class=HTMLResponse)
async def smoke_page() -> str:
    """전 구간을 브라우저에서 클릭으로 검증하는 단일 HTML 페이지."""
    return _SMOKE_HTML


@router.post("/smoke/echo")
async def smoke_echo(
    body: EchoIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """텍스트 → 가짜 LLM(에코) → 입력과 같으면 'ok' → smoke_checks 저장.

    project_id 를 주면 그 프로젝트가 현재 사용자 소유인지 검증(모든 프로젝트 대상).
    project_id 가 없으면(null) 프로젝트 없이도 동작.
    """
    if body.project_id is not None:
        project = await ProjectRepository(session).get_by_id(body.project_id)
        assert_owned(project, user)

    # 나중에 fake_llm_roundtrip 자리에 진짜 LLM이 들어가면, 판정 로직은 그대로 재사용된다.
    llm_output = await fake_llm_roundtrip(body.text)
    verdict = "ok" if llm_output == body.text else "mismatch"

    session.add(
        SmokeCheck(
            user_id=user.id,
            project_id=body.project_id,
            input_text=body.text,
            response=verdict,
        )
    )
    await session.commit()
    return {"result": verdict, "llm_output": llm_output}


# ── 자체 테스트 페이지 (외부 라이브러리 없음, 실제 엔드포인트 호출) ──────────────
_SMOKE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Glitch — 스모크 테스트</title>
<style>
  body { font-family: system-ui, "Malgun Gothic", sans-serif; max-width: 640px;
         margin: 32px auto; padding: 0 16px; background:#0f1117; color:#e7e9ee; }
  h1 { font-size: 22px; }
  .box { border:1px solid #2a2f3c; border-radius:10px; padding:16px; margin:14px 0; background:#181b24; }
  .box h2 { font-size:15px; margin:0 0 10px; color:#9aa3b2; }
  input, textarea, select { width:100%; box-sizing:border-box; padding:9px; margin:4px 0 10px;
    background:#0f1117; border:1px solid #2a2f3c; border-radius:6px; color:#e7e9ee; font:inherit; }
  button { padding:9px 16px; border:0; border-radius:6px; background:#6c8cff; color:#fff;
    font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .muted { color:#9aa3b2; font-size:13px; }
  .result { font-size:22px; font-weight:700; margin-top:8px; }
  .result .ok { color:#43c59e; } .result .bad { color:#ff5c5c; }
  .echo { font-size:13px; color:#9aa3b2; margin-top:6px; word-break:break-all; }
  #log { white-space:pre-wrap; font-size:13px; color:#9aa3b2; border-top:1px dashed #2a2f3c;
    margin-top:16px; padding-top:12px; }
  .err { color:#ff5c5c; }
  .ok { color:#43c59e; }
</style>
</head>
<body>
  <h1>Glitch — 스모크 테스트</h1>
  <p class="muted">텍스트를 가짜 LLM(에코)에 보내 <b>입력과 같으면 "ok"</b>를 돌려받고 DB에 저장합니다.
  내 프로젝트라면 어느 것이든(또는 프로젝트 없이) 됩니다. 나중에 에코 자리에 진짜 LLM이 들어갑니다.</p>

  <div class="box">
    <h2>1. 로그인</h2>
    <input id="email" type="email" value="cho@example.com" />
    <input id="password" type="password" value="glitch123" />
    <button id="btn-login">로그인</button>
    <div id="login-state" class="muted"></div>
  </div>

  <div class="box">
    <h2>2. 프로젝트 선택 (모든 프로젝트 대상)</h2>
    <select id="project" disabled></select>
    <div id="project-state" class="muted"></div>
  </div>

  <div class="box">
    <h2>3. LLM에 보낼 텍스트</h2>
    <textarea id="text" rows="4">안녕하세요, 스모크 테스트 글입니다.</textarea>
    <button id="btn-send" disabled>전송</button>
    <div id="result" class="result"></div>
    <div id="echo" class="echo"></div>
  </div>

  <div id="log"></div>

<script>
  let token = null;

  const $ = (id) => document.getElementById(id);
  const logEl = $("log");
  function log(msg, cls) {
    const line = document.createElement("div");
    if (cls) line.className = cls;
    line.textContent = msg;
    logEl.appendChild(line);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!res.ok) {
      const detail = (data && data.detail) || ("HTTP " + res.status);
      throw new Error(detail);
    }
    return data;
  }

  const authHeaders = () => ({ "Content-Type": "application/json", "Authorization": "Bearer " + token });

  $("btn-login").onclick = async () => {
    try {
      log("로그인 요청...");
      const d = await api("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: $("email").value, password: $("password").value }),
      });
      token = d.access_token;
      $("login-state").innerHTML = "<span class='ok'>로그인 성공: " + d.user.name + "</span>";
      log("로그인 OK", "ok");
      await loadProjects();
    } catch (e) {
      $("login-state").innerHTML = "<span class='err'>실패: " + e.message + "</span>";
      log("로그인 실패: " + e.message, "err");
    }
  };

  // 로그인한 사용자의 프로젝트들을 드롭다운으로 (모든 프로젝트 대상)
  async function loadProjects(selectId) {
    try {
      const d = await api("/projects?page=1", { headers: authHeaders() });
      const sel = $("project");
      let html = "<option value=''>(프로젝트 없이)</option>";
      (d.items || []).forEach((p) => {
        html += "<option value='" + p.id + "'>" + escapeHtml(p.name) + "</option>";
      });
      html += "<option value='__new__'>＋ 새 프로젝트 만들기…</option>";
      sel.innerHTML = html;
      sel.disabled = false;
      if (selectId) sel.value = selectId;
      $("btn-send").disabled = false;
      $("project-state").textContent = "프로젝트 " + (d.items ? d.items.length : 0) + "개 로드됨";
    } catch (e) {
      $("project-state").innerHTML = "<span class='err'>프로젝트 로드 실패: " + e.message + "</span>";
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/'/g,"&#39;");
  }

  // '새 프로젝트 만들기' 선택 시 생성
  $("project").onchange = async () => {
    const sel = $("project");
    if (sel.value !== "__new__") return;
    const name = prompt("새 프로젝트 이름:");
    if (!name || !name.trim()) { sel.value = ""; return; }
    try {
      const p = await api("/projects", {
        method: "POST", headers: authHeaders(), body: JSON.stringify({ name: name.trim() }),
      });
      log("프로젝트 생성 OK: " + p.id, "ok");
      await loadProjects(p.id);
    } catch (e) {
      sel.value = "";
      $("project-state").innerHTML = "<span class='err'>생성 실패: " + e.message + "</span>";
    }
  };

  $("btn-send").onclick = async () => {
    try {
      const pid = $("project").value;
      const projectId = (pid && pid !== "__new__") ? pid : null;
      log("텍스트 → LLM(에코) 왕복...");
      const d = await api("/smoke/echo", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ project_id: projectId, text: $("text").value }),
      });
      const cls = d.result === "ok" ? "ok" : "bad";
      $("result").innerHTML = "결과: <span class='" + cls + "'>" + d.result + "</span>";
      $("echo").textContent = "LLM 응답(echo): " + d.llm_output;
      log("완료 — DB 저장됨. result=" + d.result + (projectId ? " (project " + projectId + ")" : " (프로젝트 없음)"), "ok");
    } catch (e) {
      $("result").innerHTML = "<span class='bad'>실패: " + escapeHtml(e.message) + "</span>";
      $("echo").textContent = "";
      log("전송 실패: " + e.message, "err");
    }
  };
</script>
</body>
</html>"""

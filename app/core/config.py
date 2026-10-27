"""환경 의존값은 전부 여기로. 코드에 하드코딩/비밀값 금지 (CLAUDE.md 규칙)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # DB
    database_url: str = "postgresql+asyncpg://glitch:glitch@localhost:5432/glitch"
    database_url_sync: str = "postgresql+psycopg2://glitch:glitch@localhost:5432/glitch"

    # 인증(JWT)
    jwt_secret: str = "change-me-in-production-please-32chars-min"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # 파이프라인 주입
    pipeline_mode: str = "fake"  # fake | local | remote | replay
    pipeline_remote_url: str = ""
    # replay 모드: 단계(추출/검수)마다 기다리는 시간(초) — 진행 상태가 화면에 보이게
    replay_delay_seconds: float = 3.0

    # 분석 작업 큐: inline(서버 프로세스 안에서 실행 — 테스트/단순 개발용)
    #            | arq(Redis 큐 + 별도 워커 프로세스 — 서버 재시작에도 작업 보존,
    #                  수평 확장 가능, 긴 LLM 호출이 API 서버를 점유하지 않음)
    queue_mode: str = "inline"
    redis_url: str = "redis://127.0.0.1:6379/0"  # compose 가 IPv4 루프백에만 연다(localhost=::1 이면 멈춤)
    # arq 작업 1건 상한(초). 파이프라인 HTTP 타임아웃(remote.py 300초)보다 넉넉해야 한다 —
    # 검수는 임베딩 + LLM 2회라 300초를 넘길 수 있다. 넘으면 arq 가 작업을 끊는다.
    job_timeout_seconds: int = 900
    # 진행 중(extracting/reviewing) 회차가 이 시간(분) 넘게 안 바뀌면 워커가 죽은 것으로 본다.
    # 그 회차에 새 분석 요청이 오면 failed 로 기록하고 받아준다(영구 409 방지).
    # 실제 기준은 max(이 값, job_timeout_seconds//60 + 5) — 살아 있는 작업을 고착으로 오판하지 않게.
    analysis_stale_minutes: int = 20

    @property
    def analysis_stale_threshold_minutes(self) -> int:
        return max(self.analysis_stale_minutes, self.job_timeout_seconds // 60 + 5)

    # CORS (쉼표 구분 문자열 → 리스트)
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # 시드 데이터
    seed_on_startup: bool = True

    # ⚠️ SMOKE TEST(임시) — 진짜 LLM 붙으면 이 줄 삭제. app/smoke/README.md 참조
    enable_smoke: bool = True

    # ── 기능 플래그 (켜고 끄기) ──────────────────────────────
    enable_subscription: bool = True
    enable_sharing: bool = True
    enable_chat: bool = True
    enable_notifications: bool = True
    enable_firebase_auth: bool = False  # 구글 로그인(Firebase ID 토큰) 교환 엔드포인트

    # ── Firebase 검증기 주입: google(실검증) | fake(테스트 전용) ──
    firebase_mode: str = "google"
    firebase_project_id: str = ""

    # ── 교체 가능 인프라 ────────────────────────────────────
    email_mode: str = "console"      # console | smtp(추후)
    storage_mode: str = "local"      # local | s3(추후)
    upload_dir: str = "uploads"      # 썸네일/원문 파일 저장 루트(local 모드)
    # 회차 업로드 허용 확장자 (파서 레지스트리에 등록된 것)
    allowed_chapter_exts: str = "txt,docx,md,pdf"
    # 회차 업로드 상한 — 공개 터널에서 대용량 업로드로 메모리를 소진하지 못하게
    max_upload_bytes: int = 10 * 1024 * 1024   # 파일 10MB
    max_chapter_chars: int = 500_000           # 추출/입력 텍스트 50만 자
    max_thumbnail_bytes: int = 5 * 1024 * 1024  # 프로젝트 썸네일 이미지 5MB

    # 레이트리밋(분당, IP별) — 0이면 비활성. /auth/*는 무차별 대입 방지용으로 별도.
    rate_limit_per_minute: int = 240
    rate_limit_auth_per_minute: int = 30
    # 재설정/공유 링크에 쓰는 외부 접근 URL
    public_base_url: str = "http://localhost:8000"
    reset_token_expire_minutes: int = 60
    # 채팅 어시스턴트 주입: fake | remote(추후)
    chat_mode: str = "fake"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_chapter_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_chapter_exts.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

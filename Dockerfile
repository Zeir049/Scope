# Glitch 백엔드 이미지 — API 서버와 워커가 같은 이미지를 쓴다 (command만 다름).
# 빌드/실행은 docker-compose.prod.yml 참조:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/glitch

# 의존성 레이어 분리: pyproject의 dependencies만 먼저 설치해서
# 소스가 바뀌어도 의존성 설치 레이어는 캐시되게 한다.
COPY pyproject.toml ./
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; open('/tmp/req.txt','w').write('\n'.join(deps))" \
    && pip install -r /tmp/req.txt

# 애플리케이션 소스 (+ 정적 프론트 — 프론트가 갱신되면 재빌드)
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY frontend ./frontend
RUN pip install --no-deps .

EXPOSE 8000

# 기본 = API 서버. 워커는 compose에서 command를 arq로 바꿔 띄운다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

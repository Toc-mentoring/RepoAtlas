# RepoAtlas 서버 배포

EC2 같은 Linux 서버 한 대에 Docker Compose로 다섯 개 서비스를 띄웁니다. 명령은 모두 `infra/`에서 실행합니다.

| 서비스 | 역할 | 외부 포트 |
|---|---|---|
| `db` | PostgreSQL 16, 데이터는 `pgdata` 볼륨 | 없음 |
| `migrate` | `alembic upgrade head` 실행 후 종료 | 없음 |
| `api` | FastAPI (uvicorn :8000) | 없음 |
| `worker` | `python -m worker.main`, DB 큐의 분석 작업 처리 | 없음 |
| `web` | Nginx: 프론트 정적 파일 + `/api`, `/openapi.json`, `/healthz` 프록시 | `80` (`WEB_PORT`) |

시작 순서는 `db`(healthy) → `migrate`(정상 종료) → `api`·`worker` → `web`(api healthy)입니다. 프론트와 API가 같은 출처라 CORS 설정은 필요 없습니다.

## 사전 준비

- Docker Engine과 Compose 플러그인 (`docker compose version`), `sudo systemctl enable docker`
- 메모리 2GB 이상 권장. 1GB면 swap 2GB 추가
- 80번 포트 확보. Apache가 떠 있으면 `sudo systemctl disable --now apache2`(Amazon Linux는 `httpd`). Apache를 유지해야 하면 `.env`에 `WEB_PORT=8080`을 넣고 Apache에서 8080으로 프록시
- 보안 그룹 인바운드는 80(필요 시 443)과 제한된 22만 엽니다. 5432·8000은 열지 않습니다

## 최초 배포

```bash
git clone https://github.com/Toc-mentoring/RepoAtlas.git ~/RepoAtlas
cd ~/RepoAtlas/infra
cp .env.example .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
vi .env                       # GITHUB_TOKEN 입력
chmod 600 .env

docker compose up -d --build
docker compose ps             # migrate: Exited (0), 나머지: running / healthy
docker compose logs migrate   # Running upgrade  -> 0001
curl -i http://localhost/healthz              # 200 {"status":"ok"}
curl -s http://localhost/api/v1/repositories  # {"items":[],...}
```

`/healthz`는 DB에 `SELECT 1`까지 확인하며, DB에 연결할 수 없으면 503을 반환합니다.

## DB 연동 테스트 (선택, 배포 검증용)

운영 DB와 분리된 테스트 DB에서 실행합니다. 테스트는 임시 스키마를 만들고 끝나면 지웁니다.

```bash
docker compose exec db createdb -U repoatlas repoatlas_test
docker compose run --rm --no-deps -u root \
  -e TEST_DATABASE_URL="postgresql+psycopg://repoatlas:$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2)@db:5432/repoatlas_test" \
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  -v "$PWD/..:/src" -w /src api \
  sh -c "uv sync --locked && uv run pytest -q --ignore=worker/tests/test_live_github.py"
```

## 운영

| 상황 | 명령 |
|---|---|
| 로그 | `docker compose logs -f --tail=200 api worker` |
| 상태 | `docker compose ps` |
| 재시작 | `docker compose restart worker` |
| 새 코드 배포 | `git pull && docker compose up -d --build` (migration이 먼저 실행됨) |
| DB 백업 | `docker compose exec db pg_dump -U repoatlas repoatlas > backup-$(date +%F).sql` |
| 롤백 | `git checkout <이전 커밋> && docker compose up -d --build` |
| 중지 | `docker compose down` (데이터 유지) |

- `docker compose down -v`는 DB 볼륨을 지워 모든 분석 결과가 사라집니다.
- migration이 포함된 배포 전에는 백업부터 합니다. 코드 롤백은 migration을 되돌리지 않습니다.
- 프론트는 반드시 `pnpm build:backend`(real 모드)로 빌드됩니다. `web.Dockerfile`이 이를 처리하며, 화면 상단 배지가 "API 환경"이면 정상입니다.
- 외부 RDS를 쓰려면 `db` 서비스를 빼고 `DATABASE_URL`만 바꿉니다.

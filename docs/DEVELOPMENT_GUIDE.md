# 개발 착수·협업 가이드 (DEVELOPMENT_GUIDE)

[← README](../README.md) · [21일 일정](PROJECT_PLAN.md) · [API 명세](API_SPEC.md) · [DB 스키마](DB_SCHEMA.md)

## 1. 이 문서 읽고 무엇부터 할까?

1. [README](../README.md)에서 사용자 목표, 5종 다이어그램, Must/Should를 확인.
2. [API_SPEC](API_SPEC.md)의 12개 업무용 API 및 GraphDTO 계약을 팀에서 합의.
3. [DATABASE_OPERATIONS](DATABASE_OPERATIONS.md)의 명령으로 9개 테이블 migration 적용.
4. [WORKER](WORKER.md)의 명령으로 분석 Worker 또는 DB 없는 JSON 분석 실행.
5. 프론트팀은 mock GraphDTO를 이용하여 그래프 화면 선개발.
6. Day 7/14/20 통합 점검. Should 범위는 Must 완료 후 착수.

## 2. 권장 소스 디렉터리 (향후 구현할 목표 구조)

```text
RepoAtlas/
├── README.md
├── docs/
│   ├── FEATURE_SPEC.md
│   ├── TECH_STACK.md
│   ├── ARCHITECTURE.md
│   ├── CODE_ANALYSIS.md
│   ├── API_SPEC.md
│   ├── DB_SCHEMA.md
│   ├── ERD.md
│   ├── PROJECT_PLAN.md
│   └── DEVELOPMENT_GUIDE.md
├── backend/
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, health
│   │   ├── api/v1/
│   │   │   ├── repositories.py
│   │   │   ├── analyses.py
│   │   │   └── diagrams.py
│   │   ├── schemas/                # Pydantic request/response DTO
│   │   ├── models/                 # SQLAlchemy DB entities
│   │   ├── services/               # GitHub API, queue, diagram projection
│   │   └── db/                     # Session, transaction
│   └── tests/
├── worker/
│   ├── main.py                     # PostgreSQL queue polling
│   ├── github.py                   # commit-pinned archive
│   ├── archive.py                  # safe ZIP validation and index
│   ├── analyzer.py                 # analysis pipeline
│   ├── runner.py                   # child-process time limit
│   ├── cli.py                      # database-free JSON output
│   ├── jobs.py                     # PostgreSQL queue and recovery
│   ├── parsers/
│   │   ├── python_ast.py
│   │   ├── javascript_ts.py
│   │   ├── sql_ddl.py
│   │   └── config_facts.py
│   ├── resolvers/                  # Python, JS/TS module paths
│   ├── persistence.py              # normalized metadata commit
│   └── tests/fixtures/
├── frontend/
│   ├── src/
│   │   ├── api/                    # typed client, fetch functions
│   │   ├── pages/                  # RepositoryList, RepositoryDetail, RunViewer
│   │   ├── features/diagrams/      # ReactFlow, Dagre, node components
│   │   ├── features/explorer/      # file tree/search
│   │   └── components/             # status/error/warning views
│   ├── package.json
│   └── src/**/*.test.tsx
├── infra/
│   └── nginx.conf
├── compose.yaml
├── pyproject.toml
├── uv.lock
└── .env.example
```

DB 모델·migration과 Worker는 구현되어 있습니다. 위 구조 중 FastAPI, 프론트엔드, Compose/Nginx 관련 파일은 개발 목표입니다.

## 3. 환경 변수 계약 (.env.example 설계)

아래 목록에는 향후 API·배포용 설정도 포함됩니다. 현재 Worker가 읽는 변수는 [WORKER](WORKER.md)에 명시되어 있으며, `APP_ENV`, `API_PREFIX`, `WORKER_CONCURRENCY`, `ALLOWED_GITHUB_HOST`는 아직 적용되지 않습니다.

```dotenv
DATABASE_URL=postgresql+psycopg://repoatlas:change-me@db:5432/repoatlas
GITHUB_TOKEN=                  # 공개 저장소 API rate limit 완화용; 선택
APP_ENV=development
API_PREFIX=/api/v1
WORKER_CONCURRENCY=1
MAX_ARCHIVE_BYTES=536870912
MAX_EXTRACTED_BYTES=2147483648
MAX_FILES=100000
MAX_SOURCE_FILE_BYTES=1048576
ANALYSIS_TIMEOUT_SECONDS=900
ALLOWED_GITHUB_HOST=github.com
```

- **비밀값**은 `.env`로 관리하되 Git에 업로드하지 않음; `.env.example`은 테스트용 플레이스홀더만 기록.
- `DATABASE_URL`의 `change-me`는 반드시 변경. 배포에서는 DB/Worker 네트워크를 외부에 공개하지 않음.
- Analyzer가 참조하는 타 프로젝트의 `.env`는 **내용을 저장하거나 출력하지 않음**.

## 4. 로컬 개발 시작 절차

```bash
uv sync --locked
export DATABASE_URL='postgresql+psycopg://repoatlas:비밀번호@localhost:5432/repoatlas'
uv run alembic -c backend/alembic.ini upgrade head
uv run python -m worker.main
```

PostgreSQL은 별도로 준비하고 `.env`의 값은 프로세스 환경에 직접 주입합니다. DB 없는 JSON 분석은 [WORKER](WORKER.md)를 참고합니다. FastAPI, 프론트엔드, Docker Compose는 아직 실행할 수 없습니다.

## 5. 프론트↔백엔드 데이터 흐름

```mermaid
sequenceDiagram
  participant UI as React
  participant Q as TanStack Query
  participant API as FastAPI
  UI->>Q: repository 등록 mutation
  Q->>API: POST /api/v1/repositories
  API-->>Q: repo_id
  UI->>Q: 분석 시작 mutation
  Q->>API: POST /api/v1/repositories/{id}/analyses
  API-->>Q: run_id
  loop 2초, terminal 상태까지
    Q->>API: GET /api/v1/analyses/{run_id}
    API-->>Q: status + progress
  end
  Q->>API: GET /api/v1/analyses/{run_id}/diagram-types
  API-->>Q: availability 목록
  UI->>Q: 종류 + filter 선택
  Q->>API: POST /api/v1/analyses/{run_id}/diagrams
  API-->>Q: GraphDTO nodes+edges
  Q-->>UI: React Flow 변환·렌더
```

**공통 GraphDTO:** 프론트는 서버가 내려준 `nodes[].id`, `edges[].source`, `edges[].target`만을 식별자로 사용하며, Dagre `position` 계산은 프론트가 담당. API 응답에 미리 계산한 픽셀 좌표를 저장하지 않습니다.

- `Query`는 서버 응답·상태/캐시 담당; 추가 UI 상태 라이브러리는 3주 내 필수 아님.
- 사용자 클릭으로 루트 경로/depth/language가 바뀌면 다른 diagram options로 재요청.
- `availability=unsupported`는 버튼을 비활성화하고 이유를 표시.
- 클릭한 파일/심볼의 GitHub 원본은 `commit_sha` 기준 permalink.

## 6. Worker 구현 순서 (의사 코드)

```python
# 긴 DB 트랜잭션 금지: claim은 짧게 끝내고 실제 분석은 밖에서 수행
while True:
    run = claim_one_queued_run_with_skip_locked()
    if run is None:
        sleep_short_interval()
        continue
    try:
        with isolated_temp_dir() as work:
            archive = download_allowed_github_archive(run.commit_sha)
            files = safe_extract_archive(archive, work)
            nodes = index_paths(files)
            symbols, refs, ddl, facts, warnings = parse_supported_files(nodes)
            resolved_refs = resolve_local_imports(refs, nodes)
            save_results_atomically(run.id, nodes, symbols, resolved_refs, ddl, facts, warnings)
    except LimitExceeded as exc:
        mark_run_failed(run.id, code='LIMIT_EXCEEDED')
    except Exception:
        mark_run_failed(run.id, code='ANALYSIS_FAILED')
```

위 코드는 구조 설명용이며 그대로 실행되는 구현물이 아닙니다. `commit_sha`뿐 아니라 `owner/repo`는 DB에서 조회하고, GitHub API/다운로드는 host/IP allowlist를 적용합니다.

## 7. 테스트 및 PR 규칙

| 구분 | 수행 항목 | 통과 조건 |
|---|---|---|
| Unit - parser | Python/JS/TS import 및 symbol fixture | 기대 JSON 일치; 실패 이유 명시 |
| Unit - resolver | 모호/동적 경로 | unresolved로 남고 임의 엣지 없음 |
| Unit - graph | 노드·엣지 ID·evidence | source/target 모두 반환 nodes 내 존재 |
| DB test | Alembic up/down, run 간 FK | cross-run INSERT DB가 거부 |
| API test | A01~A12, 404/409/422/429 | Pydantic 응답 스키마 충족 |
| UI test | 다이어그램 선택/상태/검색 | partial/unsupported UI 정상 |
| Security test | 금지 URL, ZIP traversal, 제한 초과 | 실행/추출 차단, 오류 코드 기록 |
| Integration | 공개 fixture 등록 → 3종 시각화 | 브라우저 시연 성공 |

**Git 흐름:** `main` 배포 안정 브랜치, `develop` 통합, `feature/<topic>` 작업. MR에는 작업 요약, API/DB 영향, 테스트 결과, UI 변경 화면, 문서 동기화 여부를 기재합니다. `AGENTS.md` 또는 CI 규칙이 실제 저장소에 있다면 그 상위 정책과 충돌하지 않게 적용합니다.

## 8. 처음 투입된 팀원용 체크리스트

- [ ] 서비스 목표와 **MVP에서 제외한 기능**을 설명할 수 있다.
- [ ] `directory`, `dependency`, `symbols`가 반드시 구현할 3종임을 안다.
- [ ] `architecture`, `erd`가 근거 기반 제한형임을 안다.
- [ ] GraphDTO 및 12개 업무용 API를 읽었다.
- [ ] DB 9개 테이블의 `run_id` 스냅샷 설계를 이해했다.
- [ ] 본인이 담당할 Day/feature 및 수락 기준을 확인했다.
- [ ] 변경 시 FEATURE/API/DB/분석 규격을 같은 MR에서 갱신한다.

## 9. 외부 자료

- [FastAPI](https://fastapi.tiangolo.com/)
- [React Flow](https://reactflow.dev/)
- [GitHub REST API](https://docs.github.com/en/rest)
- [PostgreSQL](https://www.postgresql.org/docs/)
- [SQLGlot](https://sqlglot.com/)

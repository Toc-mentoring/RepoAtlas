# REST API 명세 (API_SPEC)

[← README](../README.md) · [기능](FEATURE_SPEC.md) · [DB](DB_SCHEMA.md) · [아키텍처](ARCHITECTURE.md)

## 1. 공통 계약

- Base URL: `/api/v1` · Content-Type: `application/json` · 모든 ID는 UUID(`repo_id`,`run_id`,`diagram_id`) 또는 bigint(`file_id`).
- GitHub 공개 저장소만 지원. 인증·권한 관리는 MVP 범위 밖이므로 API 서버는 rate limit과 데모 접근 제한을 갖춰야 합니다.
- List: `limit` 기본 20, 최대 100; `cursor`는 서버가 발급한 불투명 문자열. `next_cursor=null`이면 끝.
- ID를 찾지 못하면 `404`, 유효하지 않은 요청은 `422`, 사용 불가능한 상태는 `409`, 과도한 요청은 `429`.
- 에러는 통일된 형태:

```json
{
  "error": {
    "code": "ANALYSIS_NOT_READY",
    "message": "분석이 아직 완료되지 않았습니다.",
    "details": {"status": "parsing"},
    "request_id": "req-4cd1"
  }
}
```

- 상태 종류: `queued`, `fetching`, `parsing`, `resolving`, `completed`, `partial`, `failed`.
- `partial` 실행은 결과 조회 가능하나 경고를 필수로 표시; `failed`는 생성 불가.
- 심볼릭 링크는 실제 대상을 읽지 않고 `parse_status=skipped` 및 `partial` 경고로 표시.
- 분석 완료 후 `GET /diagram-types` 호출 → 선택 가능 종류만 `POST /diagrams`.
- SHA는 소스 고정 링크에 쓰는 40자 Git commit 해시로 반환. 실환경에서는 SHA-256 객체 저장소도 고려 가능하지만 GitHub 일반 SHA-1 형식을 MVP 계약으로 제한.

## 2. 엔드포인트 전체 목록 (업무용 12개 + health 1개)

| 번호 | Method | Path | 핵심 기능 | 성공 |
|---|---|---|---|---|
| A01 | POST | `/repositories` | 저장소 등록 | 201 / 기존 200 |
| A02 | GET | `/repositories` | 저장소 목록 | 200 |
| A03 | GET | `/repositories/{repo_id}` | 저장소 상세 | 200 |
| A04 | POST | `/repositories/{repo_id}/analyses` | 새 SHA 분석 큐 등록·캐시 재사용 | 202 / 재사용 200 |
| A05 | GET | `/repositories/{repo_id}/analyses` | 분석 이력 | 200 |
| A06 | GET | `/analyses/{run_id}` | 분석 상태/통계 | 200 |
| A07 | GET | `/analyses/{run_id}/nodes` | 폴더·파일 페이지 조회 | 200 |
| A08 | GET | `/analyses/{run_id}/symbols` | 함수·클래스 검색/조회 | 200 |
| A09 | GET | `/analyses/{run_id}/search` | 파일·심볼 통합 검색 | 200 |
| A10 | GET | `/analyses/{run_id}/diagram-types` | 5종 지원 여부 카탈로그 | 200 |
| A11 | POST | `/analyses/{run_id}/diagrams` | 선택 다이어그램 생성 | 201 / 캐시 200 |
| A12 | GET | `/diagrams/{diagram_id}` | 기존 그래프 조회 | 200 |
| H01 | GET | `/healthz` | health 체크 (base `/api/v1` 외부) | 200 |

> 아래 JSON ID/SHA 및 저장소 이름은 **가상 예시**이며 API 계약 모양을 보여주기 위한 값입니다.

## 3. A01 — Repository 등록

`POST /api/v1/repositories`

Body (`url` 필수, 정확히 github.com 공개 저장소 주소):

```json
{"url":"https://github.com/example-org/sample-web"}
```

201/200 응답:

```json
{
  "id":"11111111-1111-4111-8111-111111111111",
  "provider":"github",
  "owner":"example-org",
  "name":"sample-web",
  "canonical_url":"https://github.com/example-org/sample-web",
  "default_branch":"main",
  "is_existing":false,
  "created_at":"2026-11-01T06:00:00Z"
}
```

오류: `422 INVALID_REPOSITORY_URL`, `404 REPOSITORY_NOT_FOUND`, `403 GITHUB_FORBIDDEN`, `429 RATE_LIMITED`, `502 GITHUB_UNAVAILABLE`.

## 4. A02/A03 — 목록/상세

`GET /api/v1/repositories?limit=20&cursor=...&q=sample`

200 응답:

```json
{
  "items":[{"id":"11111111-1111-4111-8111-111111111111","owner":"example-org","name":"sample-web","default_branch":"main","latest_run_id":null}],
  "next_cursor":null
}
```

`GET /api/v1/repositories/{repo_id}` → 200:

```json
{
  "id":"11111111-1111-4111-8111-111111111111",
  "provider":"github","owner":"example-org","name":"sample-web",
  "canonical_url":"https://github.com/example-org/sample-web",
  "default_branch":"main", "latest_run_id":null,
  "created_at":"2026-11-01T06:00:00Z"
}
```

오류: `404 REPOSITORY_NOT_FOUND`, 422 invalid UUID. 정렬: `created_at DESC, id DESC`; cursor는 내부 keyset pagination.

## 5. A04 — 분석 실행/재분석

`POST /api/v1/repositories/{repo_id}/analyses` · Body: `{"commit_sha":"<40자리 16진수 SHA>"}`. 지정한 커밋을 분석하며 유효하지 않은 SHA는 422로 거부한다. 동일 저장소와 SHA의 진행 중 또는 완료된 분석만 재사용한다.

> 통합 필요: 현재 `develop` 백엔드는 요청 본문의 SHA를 사용하지 않고 기본 브랜치 HEAD를 분석한다. 위 요청 형식을 지원하도록 백엔드를 변경하기 전에는 실제 API 모드에서 지정 SHA 분석이 동작하지 않는다.

새 실행 `202 Accepted`:

```json
{
  "run_id":"22222222-2222-4222-8222-222222222222",
  "repository_id":"11111111-1111-4111-8111-111111111111",
  "commit_sha":"0123456789abcdef0123456789abcdef01234567",
  "status":"queued","reused":false,
  "status_url":"/api/v1/analyses/22222222-2222-4222-8222-222222222222"
}
```

동일 SHA에 이미 `completed` 또는 진행 중인 run이 있으면 새 작업 대신 해당 run 반환 `200`, `reused=true`; 동일 SHA `partial` 또는 `failed`는 재시도 시 신규 run 생성 허용.

**동시성 주의:** 여러 요청이 동시에 들어올 때 repo+SHA 진행/완료 run은 DB partial unique index 및 트랜잭션으로 한 건만 유지.

오류: `404`, `429`, `502`. URL 직접 다운로드는 이 API로 수행하지 않음.

## 6. A05/A06 — 분석 목록·상태

`GET /api/v1/repositories/{repo_id}/analyses?limit=20&cursor=...` →

```json
{
  "items":[{
    "id":"22222222-2222-4222-8222-222222222222",
    "commit_sha":"0123456789abcdef0123456789abcdef01234567",
    "status":"completed","progress":100,
    "created_at":"2026-11-01T06:01:00Z"
  }],"next_cursor":null
}
```

`GET /api/v1/analyses/{run_id}` →

```json
{
  "id":"22222222-2222-4222-8222-222222222222",
  "repository_id":"11111111-1111-4111-8111-111111111111",
  "commit_sha":"0123456789abcdef0123456789abcdef01234567",
  "status":"completed","progress":100,
  "stats":{"file_count":150,"parsed_files":70,"symbols":240,"resolved_imports":120,"unresolved_imports":12,"tables":3},
  "warnings":[],"error_code":null,"error_message":null,
  "created_at":"2026-11-01T06:01:00Z","finished_at":"2026-11-01T06:02:20Z"
}
```

진행 중에는 `progress=0..99`, 통계는 부분값일 수 있음. UI는 2초 폴링하다 `completed/partial/failed`에서 중단. 오류 `404 ANALYSIS_NOT_FOUND`.

## 7. A07 — 디렉터리/파일 노드

`GET /api/v1/analyses/{run_id}/nodes?root_path=.&depth=2&limit=100&cursor=...`

제약: depth 1..8, limit 1..100, root_path는 `.` 또는 저장소 상대경로이며 `..` 금지. 페이지 정렬 `path ASC, id ASC`.

```json
{
  "items":[
    {"id":10,"parent_id":null,"kind":"directory","path":".","name":"sample-web","language":null,"parse_status":"not_applicable"},
    {"id":11,"parent_id":10,"kind":"directory","path":"src","name":"src","language":null,"parse_status":"not_applicable"},
    {"id":12,"parent_id":11,"kind":"file","path":"src/main.py","name":"main.py","language":"python","parse_status":"parsed"}
  ],
  "next_cursor":null
}
```

`failed`인 run은 `409 ANALYSIS_NOT_READY`. `partial`은 조회 가능. `404` 잘못된 root 또는 run, `422` 필터 오류.

## 8. A08 — 심볼 조회

`GET /api/v1/analyses/{run_id}/symbols?file_id=12&kind=function&limit=50&cursor=...`

`file_id`와 `kind` 모두 선택; `kind`는 `function|class|method|interface`. `file_id` 미지정 시 실행 내 전체 목록을 페이지로 반환.

```json
{
 "items":[{"id":301,"file_id":12,"parent_symbol_id":null,"kind":"function","name":"main","qualified_name":"main","start_line":7,"end_line":15,"github_url":"https://github.com/example-org/sample-web/blob/0123456789abcdef0123456789abcdef01234567/src/main.py#L7-L15"}],
 "next_cursor":null
}
```

오류 `404` run/file 없음, `422` 필터 오류, `409` 아직 분석 중.

## 9. A09 — 파일·심볼 통합 검색

`GET /api/v1/analyses/{run_id}/search?q=User&kind=all&limit=20&cursor=...`

`q`: 2~100자, `kind=all|file|symbol`.

```json
{
  "items":[
    {"kind":"file","id":"file:12","label":"src/user.py","path":"src/user.py","line":null},
    {"kind":"symbol","id":"symbol:301","label":"UserService","path":"src/user.py","line":7}
  ],
  "next_cursor":null
}
```

텍스트 검색은 MVP에서 `ILIKE` + 범위 제한으로 시작. 데이터가 많아지면 pg_trgm을 후속 검토.

## 10. A10 — 다이어그램 가용성 카탈로그

`GET /api/v1/analyses/{run_id}/diagram-types`

```json
{
  "run_id":"22222222-2222-4222-8222-222222222222",
  "items":[
    {"type":"directory","availability":"available","reason":null},
    {"type":"dependency","availability":"available","reason":null},
    {"type":"symbols","availability":"available","reason":null},
    {"type":"architecture","availability":"partial","reason":"compose 기반 근거만 확인"},
    {"type":"erd","availability":"unsupported","reason":"해석 가능한 SQL DDL 없음"}
  ]
}
```

`available|partial|unsupported`는 분석 실행 상태와 다른 **다이어그램 가용성** 값. 실행이 `queued/running/failed`이면 `409 ANALYSIS_NOT_READY`.

## 11. A11 — 다이어그램 생성

`POST /api/v1/analyses/{run_id}/diagrams`

Body (type 필수, 나머지 옵션 기본값 적용):

```json
{
  "type":"dependency",
  "options":{"root_path":"src","language":"python","depth":2,"max_nodes":150}
}
```

- 허용 `type`: `directory`, `dependency`, `symbols`, `architecture`, `erd`.
- `symbols`일 때 **`options.file_id` 필수**. 나머지는 지원하는 필터만 수락하며 잘못된 옵션은 `422`.
- depth 1..8, max_nodes 20..300. `root_path`는 DB의 실제 경로여야 함.
- 생성 성공은 `201`, 동일 run/type/정규화된 options 캐시 적중은 `200`.
- `unsupported` type은 `409 DIAGRAM_UNSUPPORTED`; 분석 중은 `409 ANALYSIS_NOT_READY`.

201 응답 (GraphDTO):

```json
{
  "diagram_id":"33333333-3333-4333-8333-333333333333",
  "run_id":"22222222-2222-4222-8222-222222222222",
  "type":"dependency",
  "availability":"available",
  "truncated":false,
  "has_more":false,
  "nodes":[
    {"id":"file:12","type":"file","label":"main.py","data":{"path":"src/main.py","language":"python","github_url":"https://github.com/example-org/sample-web/blob/0123456789abcdef0123456789abcdef01234567/src/main.py"}},
    {"id":"file:13","type":"file","label":"user.py","data":{"path":"src/user.py","language":"python","github_url":"https://github.com/example-org/sample-web/blob/0123456789abcdef0123456789abcdef01234567/src/user.py"}}
  ],
  "edges":[
    {"id":"imports:12:13:3","source":"file:12","target":"file:13","type":"imports","data":{"certainty":"confirmed","evidence":[{"path":"src/main.py","line":3,"basis":"python_ast_import"}]}}
  ],
  "warnings":[],
  "unresolved_references":0
}
```

`nodes[].id`, `edges[].source/target`는 프론트 React Flow ID 규약과 일치해야 합니다. `architecture`의 `inferred` 엣지는 대시 선으로 표시. `erd`의 노드/간선은 `table:`/`column:` 및 `foreign_key` 타입 사용.

## 12. A12 — 다이어그램 재조회

`GET /api/v1/diagrams/{diagram_id}` → `200`에 **A11과 동일 GraphDTO**. 미존재 또는 오래된 run 삭제로 정리된 캐시 `404 DIAGRAM_NOT_FOUND`.

## 13. H01 — 상태 확인

`GET /healthz` → `200` `{ "status":"ok" }`. DB 연결 실패 등 비정상은 `503`.

## 14. 오류 코드·재시도 정책

| HTTP | error.code | 의미 | 클라이언트 처리 |
|---:|---|---|---|
| 404 | `REPOSITORY_NOT_FOUND`, `ANALYSIS_NOT_FOUND`, `DIAGRAM_NOT_FOUND` | 리소스 없음 | 목록 이동 |
| 409 | `ANALYSIS_NOT_READY` | 분석 진행 중/실패 | 상태 페이지 |
| 409 | `DIAGRAM_UNSUPPORTED` | 해당 type 근거 없음 | 제한 이유 표시 |
| 422 | `INVALID_REPOSITORY_URL`, `INVALID_FILTER` | 입력 오류 | 필드 검증 안내 |
| 429 | `RATE_LIMITED` | 서버/GitHub 이용 제한 | `Retry-After`를 읽고 재요청 |
| 502 | `GITHUB_UNAVAILABLE` | GitHub API 실패 | 재시도 안내 |
| 500 | `INTERNAL_ERROR` | 내부 서버 오류 | request_id로 서버 로그 조사 |

등록, 분석 요청 등 **쓰기를 유발하는 재시도는** 중복 방지 로직이 있어야 합니다. 사용자가 버튼을 연속 클릭해도 진행 중인 동일 SHA의 run이 늘어나지 않도록 합니다.

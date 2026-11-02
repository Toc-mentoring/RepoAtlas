# 기능 명세 (FEATURE_SPEC)

[← README](../README.md) · [API](API_SPEC.md) · [분석 규칙](CODE_ANALYSIS.md)

## 1. 핵심 사용자 시나리오

**신규 유지보수 담당자:** GitHub URL 등록 → 분석 상태 확인 → `directory`에서 관심 폴더 탐색 → `dependency`에서 연결된 파일 확인 → `symbols`에서 정의 확인 → 필요하면 `architecture`·`erd`를 열고 증거 파일로 이동.

**설계 원칙:** 전체 저장소는 크기 제한 내에서 파일 목록화하되, 브라우저는 필요한 부분만 단계적으로 로드합니다. `source_nodes`의 파일 목록과 실제 AST 분석 성공 여부는 다릅니다. 시각화는 코드의 사실과 정적 추론을 구분합니다.

## 2. 기능 우선순위 / 작업량

단위: 1명 기준 대략적 순수 개발일; 공통 인프라·통합 작업과 중복되므로 단순 합계로 일정 산출하지 말 것.

| ID | 기능 | 우선순위 | 난이도 | 추정 | 완료 기준 |
|---|---|---|---|---:|---|
| F01 | 공개 GitHub URL 등록 및 메타데이터 | Must | 중 | 1.5일 | 중복 등록 처리, 허용 URL만 수락 |
| F02 | SHA 고정 수집·진행 상태·재분석 | Must | 상 | 3일 | 새 커밋 재분석, 같은 SHA 성공 캐시 재사용, 오류 코드 |
| F03 | 전체 경로 색인, 제외/제한 표시 | Must | 중 | 1.5일 | 폴더·파일 탐색, 스캔 통계와 제한 경고 |
| F04 | Python/JS/TS 심볼 추출 | Must | 상 | 3일 | 파일별 함수·클래스·메서드·라인 정보 |
| F05 | 내부 정적 import 관계 | Must | 상 | 3일 | 해결된 관계만 실제 대상 노드 연결 |
| F06 | 3종 필수 그래프 | Must | 상 | 3.5일 | 탐색, 연결 강조, 필터 및 증거 링크 |
| F07 | `architecture` 제한형 | Should | 상 | 2일 | Compose/설정 근거만, 없으면 unsupported |
| F08 | `erd` PostgreSQL DDL 제한형 | Should | 상 | 2일 | CREATE TABLE·PK·FK, 없으면 unsupported |
| F09 | SVG/PNG 내보내기 | Should | 중 | 1일 | 범위/성능 여유 시 추가 |
| F10 | Java/C/C++ 심층 분석 | Out | 상 | - | 파일 목록만 등록 |
| F11 | AI 채팅·수정·리뷰, OAuth | Out | - | - | API/DB에 포함 금지 |

## 3. 화면 계약

| 화면/URL 예시 | 사용자 조작 | 상태/에러 | 연관 API |
|---|---|---|---|
| `/` | 저장소 URL 입력, 등록 | 422 URL 오류, 429 제한 | `POST /repositories`, `GET /repositories` |
| `/repositories/:repoId` | 분석 요청·이력 | queued/running/partial/failed | `GET /repositories/{id}`, `POST /repositories/{id}/analyses`, `GET /repositories/{id}/analyses` |
| `/runs/:runId` | 다이어그램 선택·검색·경로 필터 | 준비 중·부분지원·미지원 구분 | `GET /analyses/{id}`, `GET /analyses/{id}/diagram-types`, `POST /analyses/{id}/diagrams` |
| `/diagrams/:id` | 확대·축소, 노드 클릭, 원본 파일 링크 | `has_more` 결과가 있으면 범위 축소 안내 | `GET /diagrams/{id}`, `GET /analyses/{id}/nodes`, `GET /analyses/{id}/symbols` |

**반응형 우선순위:** 데스크톱 3패널(트리/그래프/상세) 필수, 모바일은 탐색기와 상세 패널 토글로 축소. 인증 기능은 1차 제외.

## 4. 다이어그램 요구사항

### D01 `directory` — Must
- 입력: `root_path` (기본 `.`), `depth`(1~8), `max_nodes`(20~300).
- 출력: 폴더/파일 `nodes` + 부모→자식 `contains` 간선.
- 특정 폴더를 클릭하면 `root_path`를 바꿔 다시 조회. 파일 선택 시 `symbols`와 원본 SHA URL 표시.
- 300개 넘으면 무조건 임의 생략 금지: `truncated=true`, `has_more=true`, `warnings` 제공.

### D02 `dependency` — Must
- 입력: `root_path`, `language`, `max_nodes`, `depth`.
- 출력: 내부 `resolved` 참조의 파일→파일 `imports` 간선.
- 미해결/외부 참조는 대상 노드로 가짜 연결하지 않고 상세 패널의 `unresolved_references`에 노출.
- 클릭한 파일의 입출력 참조를 강조, 원본 파일·라인으로 이동.

### D03 `symbols` — Must
- 입력: `file_id` 필수, `max_nodes`.
- 출력: 선택 파일과 그 내부 함수·클래스·메서드 및 상위 관계 `declares/contains`.
- *호출 관계(`calls`)*는 생성하지 않음. 인터페이스 등은 지원 파서가 식별한 경우 `interface`로 표시.

### D04 `architecture` — Should (제한형)
- 입력: `root_path`, `max_nodes`.
- 근거: `docker-compose.yml`, `Dockerfile`, `package.json`, FastAPI 라우터, DB 연결 설정에 대한 안전한 정적 스캔.
- `component` 및 `architecture_dependency` 관계를 표시하되 연결마다 `certainty`(`confirmed`/`inferred`)와 `evidence` 포함.
- 충분한 근거가 없으면 카탈로그 `unsupported` 및 빈 그래프/경고 반환. 폴더명만으로 실제 네트워크 연결이 있다고 단정하지 않음.

### D05 `erd` — Should (제한형)
- 입력: `max_nodes`, `root_path`.
- `*.sql`에서 PostgreSQL `CREATE TABLE`, 컬럼, PK, 명시적 FK만 우선 추출. ORM 추출은 후속.
- 테이블→컬럼 관계와 FK 간선 표시. 복합 FK는 같은 제약명과 순번으로 그룹화.
- 실제 운영 DB에 연결하지 않으며 DB의 현재 상태를 보장하지 않음. 외부 SQL 방언·파싱 실패는 경고.

## 5. 공통 노드 상세 / 근거 규칙

모든 다이어그램의 노드는 `id`, `type`, `label`, `data`를 갖고, `data.path`, `data.line`, `data.github_url`은 가능할 때 채웁니다. 관계는 `source`, `target`, `type`, `data.certainty`, `data.evidence[]`를 갖습니다. `certainty=inferred`는 UI에서 점선으로 구분합니다.

```json
{
  "id": "file:21",
  "type": "file",
  "label": "main.py",
  "data": {
    "path": "src/main.py",
    "language": "python",
    "github_url": "https://github.com/acme/demo/blob/0123456789abcdef0123456789abcdef01234567/src/main.py"
  }
}
```

**근거 URL**은 항상 해당 분석 `commit_sha`를 포함하며 UI는 내용 전체를 DB에 저장하지 않습니다.

## 6. 데이터 품질·예외

- **수집 제한:** 아카이브 크기/압축 해제 크기/파일 수 초과는 `failed` + `LIMIT_EXCEEDED`; 부분 저장 결과를 성공처럼 노출하지 않음.
- **파일 파싱 실패:** 특정 파일만 실패하면 `partial` + `parse_status=failed`, 다른 파일 결과는 표시.
- **심볼릭 링크:** 경로는 `skipped`로 색인하고 링크를 따라가지 않으며 `partial`과 경고를 표시.
- **동적 import:** `unresolved` 유지; `resolved`처럼 보이지 않음.
- **No schema:** `erd=unsupported`와 근거 부족 메시지.
- **동일 SHA 재요청:** 완료·부분 분석을 재사용할지 여부는 상태/버전 규칙에 따름. 기본 재사용은 `completed`만, `partial`은 명시적 재시도 허용.
- **브라우저 성능:** API 노드는 기본 150개, 최대 300개. 파일·노드 전체를 한 번에 내려보내지 않음.

## 7. 인수 조건 (acceptance)

- 팀원은 데모 URL에서 외부 공개 저장소를 등록하고 3개 필수 그래프를 생성할 수 있음.
- 소스코드가 없는 파일도 폴더 구조에서 빠지지 않음(제한 대상/서브모듈 제외 및 경고).
- 테스트 fixture 30개 이상의 정적 import에서 *연결했다고 주장한* 관계의 precision ≥ 95%; 커버리지도 별도 보고.
- `architecture`·`erd` 지원 불가 사례에서 허위 생성 없이 명확한 상태 제공.
- 작업 실패, 재시도, 중복 요청, 캐시, 404/409/422/429를 UI에서 구분.

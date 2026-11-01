# 코드 분석 규격 (CODE_ANALYSIS)

[← README](../README.md) · [아키텍처](ARCHITECTURE.md) · [DB](DB_SCHEMA.md) · [기능](FEATURE_SPEC.md)

## 1. 분석 범위

**현재 지원:** 공개 GitHub 저장소 기본 브랜치의 SHA 스냅샷 하나. 파일 경로 전체 인덱싱(아카이브에 포함된 파일, 제한 내) + Python/JS/JSX/TS/TSX의 정의·정적 import 분석. PostgreSQL SQL DDL 및 정적 설정은 Should.

Git submodule의 외부 내용, Git LFS 원본 파일, 바이너리 본문, 동적 실행 결과 등은 자동 분석 대상이 아니며 경고에 기록합니다. `node_modules`, `.git`, 빌드 출력 등 아카이브에 존재하면 경로 정책에 따라 색인에서 제외할지 표시해야 합니다.

ZIP의 symlink는 경로만 `skipped`로 색인합니다. 링크 대상은 읽거나 따라가지 않으며, 분석 결과에 경고를 남깁니다.

## 2. 분석 단계 인터페이스

```text
Repository Snapshot
  ├─ ArchiveFetcher -> archive_path, commit_sha
  ├─ SafeExtractor -> workspace, scan_warnings
  ├─ FileIndexer -> source_nodes(directory/file), language/parse_status
  ├─ AnalyzerRouter -> SymbolDTO[], RawReferenceDTO[], ConfigFactDTO[], SchemaDTO[]
  ├─ ReferenceResolver -> ResolvedReferenceDTO[]
  └─ AtomicPersister -> analysis_runs + child tables
```

```python
# 구현용 Python typing 계약 (의사 코드)
@dataclass
class SymbolDTO:
    file_path: str
    parent_qualified_name: str | None
    name: str
    kind: Literal['function', 'class', 'method', 'interface']
    start_line: int
    end_line: int

@dataclass
class ReferenceDTO:
    source_path: str
    raw_ref: str
    source_line: int
    kind: Literal['imports']
    target_path: str | None
    resolution_status: Literal['resolved', 'unresolved', 'external']
```

원본 파일 경로는 `/` 구분자로 정규화하고 저장소 루트 상대경로만 저장합니다. `source_nodes.path='.'`은 루트 디렉터리이며 `kind='directory'`입니다.

## 3. 언어별 추출 규칙

| 언어 | 파서 | 심볼 | import 해석 | 한계 |
|---|---|---|---|---|
| Python | `ast.parse` | FunctionDef, AsyncFunctionDef, ClassDef, 클래스 내부 함수=method | `import x`, `from x import y`, `from . import x` 등 정적 내부 후보 | 동적 import, import path 변경, 설치 패키지 환경 |
| JS/JSX | Tree-sitter JS | function/class, arrow-function 변수 선언(선택), export | `import '...'`, `export ... from`, 정적 `require('...')` | 계산된 require, bundler alias |
| TS/TSX | Tree-sitter TS/TSX | function/class/method/interface | 위와 동일한 정적 상대경로 우선 | `tsconfig paths`, 타입 공간 참조·모듈 해석의 완전성 |
| SQL | SQLGlot (PostgreSQL dialect) | 테이블, 컬럼, PK/FK | 명시적 FK만 | 함수/동적 SQL/전체 마이그레이션 이력 해석 제외 |
| Java/C/C++ | 없음(MVP) | 목록만 | 없음 | 지원 언어가 아닌 파일을 무조건 parse failed로 표기하지 않음 |

`parse_status`: `not_applicable`(디렉터리/비코드 파일), `unsupported`(미지원 소스), `parsed`, `failed`, `skipped`(크기 제한 등).

### Python 해석 예시

```text
src/
  main.py
  services/
    __init__.py
    users.py
```

```python
# src/main.py
from services.users import get_user
```

Resolver는 `services.users`를 workspace 후보 경로와 매칭하여 `src/services/users.py` 또는 패키지 `__init__.py`를 찾습니다. `src`가 실제 Python import root인지 확실하지 않으면 제한적 추론을 경고로 기록하거나 unresolved로 둡니다. 대상 식별이 불가능할 때 가짜 간선을 만들지 않습니다.

### JS/TS 해석 예시

```ts
// src/App.tsx
import { Header } from './components/Header'
```

후보: `src/components/Header.ts`, `.tsx`, `.js`, `.jsx`, `src/components/Header/index.ts(x)` 순으로 명시적 규칙을 적용합니다. **후보가 둘 이상 동일 우선순위로 충돌하면 unresolved**로 남깁니다. `@/components/Header` 같은 별칭은 첫 MVP에서 기본적으로 미지원이며 경고로 남깁니다.

## 4. 파일 의존성 의미

`A -> B (imports)`는 **A 파일에서 B로 해석되는 정적 import 문을 찾았다**는 뜻입니다. 런타임 호출·실제 데이터 흐름·빌드 결과의 실행 의존성을 보장하지 않습니다. 파서가 추출한 raw import 문자열과 원본 줄 번호는 함께 저장합니다.

```json
{
  "source_file": "src/App.tsx",
  "raw_ref": "./components/Header",
  "source_line": 3,
  "target_file": "src/components/Header.tsx",
  "resolution_status": "resolved",
  "kind": "imports"
}
```

**외부 패키지**(`react`, `fastapi` 등)는 `external`, **대상을 못 찾았거나 모호**한 참조는 `unresolved`. 둘 다 `target_file_id=null`이며 그래프에서 내부 파일 노드로 강제 연결하지 않습니다.

## 5. 클래스·함수 구조 vs 함수 호출 그래프

`symbols` 다이어그램은 `file -> class -> method` 또는 `file -> function` 계층만 나타냅니다. `foo()`가 `bar()`를 호출한다는 call graph는 동적 디스패치, 상속, 런타임 import 등을 고려해야 하므로 **MVP 범위 밖**입니다.

노드 표시: 이름, 종류, 정의 시작/끝 라인, 언어, SHA로 고정된 원본 링크. 소스 코드 원문은 저장하지 않습니다.

## 6. 시스템 아키텍처 다이어그램 (제한형)

작업 단계에서 안전하게 스캔한 **정적 사실만** `source_nodes.metadata`의 `config_facts`에 기록합니다.

| 입력 | 파싱 사실 예 | certainty |
|---|---|---|
| `docker-compose.yml`의 services | `service:web`, `service:api`, `depends_on` | 명시적 설정 관계는 confirmed, 실제 통신은 보장하지 않음 |
| `package.json` | `react`, `vite`, 실행 스크립트 키 | 프레임워크 존재는 confirmed, 시스템 연결은 별도 근거 필요 |
| FastAPI `FastAPI(...)`, `include_router` | 앱·라우터 정의 | AST에서 확인된 선언만 confirmed |
| DATABASE_URL 등 환경변수 이름 | DB 설정 사용 *가능성* | inferred; **값·비밀번호 저장 금지** |
| Dockerfile | 컨테이너 구성 요소 | 명시적 파일 존재 confirmed; 외부 배포 상태는 불명 |

**예시:** `docker-compose.yml`에서 `api`의 `depends_on: [db]`가 명시된 경우 `api -> db`를 `basis='compose_depends_on'`으로 표시. `frontend/` 폴더명만으로 `frontend -> api`는 만들지 않음. 환경 변수와 실행 스크립트 내용은 명령으로 실행하지 않습니다.

## 7. ERD 생성 규칙 (제한형)

- `.sql` 중 PostgreSQL 호환 `CREATE TABLE` DDL을 파싱. `schema.table`의 schema가 없으면 `public`으로 정규화.
- `CREATE TABLE users (id BIGINT PRIMARY KEY, ...)`, `FOREIGN KEY (user_id) REFERENCES users(id)` 같은 **정적으로 보이는 선언**만 추출.
- FK는 제약 하나당 컬럼 쌍을 `ordinal_position`으로 저장하여 복합키를 복원.
- 제약 대상 컬럼을 확정하지 못하면 `target_column_id=null`, `target_ref`에 원래 선언을 저장하고 unresolved로 표시.
- 여러 마이그레이션에 같은 테이블이 재정의/수정되는 경우 현재 최종 스키마를 보장하지 않음. 충돌시 경고 후 단일 스냅샷 결과에서 중복 병합/제외 규칙 적용.
- **운영 중인 DB 접속·테이블 자동 마이그레이션 절대 하지 않음**.

SQLAlchemy ORM 모델 등 추가 해석은 1차에서는 제외하되 `erd`가 지원되지 않는 사유를 표시합니다.

## 8. 그래프 투영 계약

DB의 AST/스키마 메타데이터를 **선택 종류의 JSON 노드·간선**으로 변환합니다. `source_node` 등의 DB PK는 공개 노드 식별자에 타입 prefix를 붙여 충돌을 방지합니다.

- node IDs: `dir:{id}`, `file:{id}`, `symbol:{id}`, `table:{id}`, `column:{id}`, `component:{hash}`.
- edge IDs: `(relation, source_id, target_id, source_line, ordinal)`의 안정적인 해시 사용.
- `data.evidence`: `{path, line, basis}` 리스트; `certainty`: `confirmed` 또는 `inferred`.
- 옵션 기본값: `depth=2`, `max_nodes=150`, 상한 `depth<=8`, `max_nodes<=300`. `symbols`에는 `file_id` 필수.
- 페이로드는 [API_SPEC](API_SPEC.md)의 `GraphDTO`를 따름.

## 9. 테스트 fixture

최소 아래 소규모 저장소들을 직접 만들고 **expected JSON**과 비교합니다.

1. Python: 절대/상대 import, 클래스 안 메서드, 동적 import, 누락 모듈.
2. JS/TS: `.js/.jsx/.ts/.tsx`, default/named import, re-export, 정적 require, alias 미해결.
3. 구조: 중첩 디렉터리, 동일 이름의 다른 파일, 비코드 파일, 이진 파일, 한글 파일명.
4. ERD: 단일 PK/FK, 복합 FK, 스키마 네임스페이스, 미지원 방언.
5. 아키텍처: Compose 2서비스+depends_on; 불충분한 설정 시 unsupported.
6. 보안: path traversal ZIP, 압축 폭탄 유사 fixture, redirect 불허, 파일 제한.

**정확도 보고:** TP/(TP+FP) precision, TP/(TP+FN) recall을 **구분**하여 수치화. 정확한 내부 import 연결 precision ≥ 95%가 목표이고 recall은 별도 보고합니다.

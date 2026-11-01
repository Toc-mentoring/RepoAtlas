# 기술 스택 결정 (TECH_STACK)

[← README](../README.md) · [아키텍처](ARCHITECTURE.md) · [개발 가이드](DEVELOPMENT_GUIDE.md)

## 1. 선정 원칙

- 21일 MVP를 위한 **단일 API + 단일 분석 Worker + PostgreSQL**. 추가 메시지 브로커·MSA·그래프 DB를 도입하지 않음.
- 신규 도구의 학습비용, 라이브러리 생태계, 보안 제한을 함께 평가.
- 실제 설치할 패키지 버전은 구현 첫날 호환성 검증 후 lockfile에 **정확히 pin**. 아래는 버전 단정 없는 기술 선정이며, 임의의 최신 버전 숫자는 쓰지 않음.

| 영역 | 선택 | 사용 목적 | 대안 및 판단 | 주의사항 |
|---|---|---|---|---|
| Frontend | React + TypeScript + Vite | SPA·타입 안전·빠른 빌드 | Next.js: SEO/SSR 불필요 | API DTO 타입 동기화 |
| UI | Tailwind CSS | 레이아웃·반응형 | CSS Modules도 가능 | 복잡한 디자인 시스템은 후속 |
| 그래프 | `@xyflow/react` | 드래그·확대·축소·선택·커스텀 노드 | D3.js: 자유도↑, 직접 구현 공수↑ | 150~300 노드로 렌더 제한 |
| 그래프 배치 | Dagre | 계층 그래프 자동 배치 | ELK: 복잡 그래프에 강하나 초기 학습 비용↑ | 루프/밀집 그래프에 시각적 한계 |
| 서버 데이터 | TanStack Query | 목록·상태 폴링·캐시 | Zustand는 UI 전역 상태가 필요하면 추후 | 서버 원본 상태는 Query만 |
| API | FastAPI + Pydantic | REST·검증·OpenAPI 문서 | Django: 초기 기능 대비 무거움 | 장시간 분석을 요청 핸들러에서 수행하지 않음 |
| DB 액세스 | SQLAlchemy + Alembic | 관계 모델·트랜잭션·마이그레이션 | raw psycopg: 보일러플레이트↑ | ORM 모델과 SQL DDL 일치 검증 |
| Python 분석 | Python 표준 `ast` | 함수·클래스·import 추출 | Tree-sitter Python 가능 | Python 문법 버전 차이·동적 import 미지원 |
| JS/TS 분석 | Tree-sitter JS/TS grammars | `.js/.jsx/.ts/.tsx` 선언·정적 import | Babel/TypeScript compiler: 별도 Node 실행 필요하나 해석력↑ | 완전한 타입 해석·tsconfig alias는 제외 |
| SQL 분석 | SQLGlot | PostgreSQL DDL에서 정적 스키마 추출 | regex: SQL 문법 불안정 | 모든 방언·복합 제약 완전 지원은 보장하지 않음 |
| 설정 파싱 | 표준 `json` + PyYAML `safe_load` | package/compose 구조 감지 | 직접 regex 비권장 | 외부 링크/환경변수 평가 금지 |
| 데이터·작업 큐 | PostgreSQL | 분석 스냅샷·노드/관계·잡 상태 | Redis+Celery: 규모 확장 시 고려 | `FOR UPDATE SKIP LOCKED`, heartbeat |
| 수집 | GitHub REST + SHA 고정 ZIP | 공개 저장소 메타데이터·아카이브 | git clone: 네이티브 Git 관리 필요 | redirect allowlist, zip slip, size 제한 |
| 배포 | Docker Compose + Nginx | 단일 서버 4개 서비스 배포 | Kubernetes: 3주에 과도 | Worker rootless/권한 최소화 |
| 테스트 | pytest + httpx + Vitest | 파서/API/뷰 단위·통합 테스트 | Playwright E2E는 시연용 1경로 추가 가능 | 분석 fixture 고정 SHA 사용 |

## 2. 언어별 기술 의사결정

| 언어 | 파서 | 추출 범위 | 의존성 해석 가능 범위 | MVP |
|---|---|---|---|---|
| Python `.py` | 표준 `ast` | `FunctionDef`, `AsyncFunctionDef`, `ClassDef`, 메서드 | 정적 `import`·`from ... import`, 상대 모듈 | Must |
| JS `.js/.jsx` | Tree-sitter JS | 함수·클래스·선언, static import/export | 상대경로 import/re-export, 정적 리터럴 `require()` | Must |
| TS `.ts/.tsx` | Tree-sitter TS/TSX | 위 항목·interface | 상대경로 및 확장자 해석 | Must |
| SQL `.sql` | SQLGlot | PostgreSQL DDL 테이블·컬럼·PK·FK | 명시적 FK만 | Should |
| Java/C/C++ | Tree-sitter로 파싱 가능 | 파일 경로만 표시 | resolver 비용으로 1차 제외 | Out |

## 3. Worker 선택 이유

FastAPI `BackgroundTasks`는 가벼운 후처리에 적합하지만, 저장소 수집/파싱은 시간·CPU·메모리와 실패 복구가 중요하므로 별도 Python 프로세스로 분리합니다. API는 작업을 DB에 INSERT하고 `202 Accepted`를 반환합니다. Worker는 DB 행을 하나 점유하여 분석하고 heartbeat을 갱신합니다. Redis를 추가하지 않고도 단일 서버·낮은 동시성에서는 충분합니다.

- 동시 분석 작업 수: 기본 1개(서버 상황 따라 확장).
- 실패 시 `failed`, 경고가 있지만 활용 가능할 때 `partial`.
- API와 Worker가 같은 DB·분석 모델 패키지를 공유하도록 monorepo 구성.

## 4. 버전·라이선스 확인 체크리스트

Day 1에 `python --version`, `node --version`, `pip index versions`, 패키지 lockfile, PostgreSQL 이미지 태그와 라이선스를 확정합니다. npm `package-lock.json`, Python `uv.lock` 또는 `requirements.lock` 중 하나를 사용합니다. 지원되지 않는 조합은 Day 1에 교체합니다.

공식 자료:
- [React Flow API](https://reactflow.dev/api-reference/react-flow)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [GitHub REST: Repository archive](https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-zip)
- [SQLGlot API](https://sqlglot.com/sqlglot.html)

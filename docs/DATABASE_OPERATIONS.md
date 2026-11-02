# RepoAtlas PostgreSQL 설치와 마이그레이션

RepoAtlas는 PostgreSQL 16 이상과 Python 3.11~3.13을 사용합니다. API와 Worker는 같은 데이터베이스와 같은 마이그레이션 버전을 사용해야 합니다. 아래 명령은 저장소 루트에서 실행합니다.

## 최초 준비

운영 PostgreSQL에 전용 계정과 빈 데이터베이스를 준비합니다. 예를 들어 서버 관리자는 PostgreSQL 시스템 계정으로 다음 명령을 실행할 수 있습니다.

```bash
sudo -u postgres createuser --pwprompt repoatlas
sudo -u postgres createdb --owner=repoatlas repoatlas
```

계정은 해당 DB에 스키마와 테이블을 생성할 권한이 필요합니다. 기존 DB나 별도 권한 정책을 사용하는 환경은 관리자가 전용 DB와 계정을 준비합니다. 운영 자격 증명은 환경 변수나 비밀 관리 도구로 주입하고 Git에 저장하지 않습니다.

```bash
uv sync --locked --no-dev
export DATABASE_URL='postgresql+psycopg://repoatlas:비밀번호@DB호스트:5432/repoatlas'
uv run --no-dev alembic -c backend/alembic.ini upgrade head
uv run --no-dev alembic -c backend/alembic.ini current
```

Windows PowerShell에서는 `export` 대신 `$env:DATABASE_URL = 'postgresql+psycopg://...'`를 사용합니다. URL에 들어가는 비밀번호의 `@`, `:`, `%` 등 특수 문자는 URL 인코딩합니다. `.env.example`은 예시이며 명령은 `.env`를 자동으로 읽지 않습니다.

## 배포 시

1. 운영 DB 백업을 확인하고 API와 Worker에 호환되는 코드 버전을 배포합니다.
2. 하나의 배포 프로세스에서 `uv run --no-dev alembic -c backend/alembic.ini upgrade head`를 실행합니다. 여러 인스턴스가 동시에 마이그레이션하지 않게 합니다.
3. `uv run --no-dev alembic -c backend/alembic.ini current`로 적용 버전을 확인하고 API와 Worker를 시작합니다.

DB 연결이 되지 않거나 마이그레이션이 실패하면 애플리케이션을 시작하지 말고 오류를 확인합니다.

## 개발 및 복구

```bash
uv sync --locked
uv run alembic -c backend/alembic.ini history
uv run alembic -c backend/alembic.ini check
uv run alembic -c backend/alembic.ini revision --autogenerate -m 'describe change'
uv run alembic -c backend/alembic.ini upgrade head
```

생성된 revision의 제약과 데이터 변환은 검토 후 커밋합니다. `check`는 모델과 현재 DB의 차이를 검사합니다. 초기 revision은 설계된 9개 테이블을 생성하며, 동일한 migration을 새 서버에 적용해 같은 구조를 재현합니다.

개발 DB에서 바로 이전 revision으로 되돌리는 명령은 `uv run alembic -c backend/alembic.ini downgrade -1`입니다. 초기 revision을 되돌리면 테이블과 데이터가 삭제되므로 운영 DB에서 실행하기 전에 백업과 복구 계획이 필요합니다.

실제 PostgreSQL 통합 테스트는 별도 테스트 DB를 지정해 실행합니다. 테스트는 해당 DB에 임시 스키마를 생성하고 종료 시 삭제합니다.

```bash
export TEST_DATABASE_URL='postgresql+psycopg://repoatlas:비밀번호@localhost:5432/repoatlas_test'
uv run pytest backend/tests
```

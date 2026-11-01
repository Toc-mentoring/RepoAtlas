# Worker 실행 가이드

## DB 없이 GitHub 저장소 분석하기

Python 3.11~3.13과 `uv`를 준비한 뒤 저장소 루트에서 실행합니다.

```bash
uv sync --locked
uv run python -m worker.cli https://github.com/psf/requests --output analysis-output/requests.json
```

URL만 입력하면 기본 브랜치의 현재 커밋을 고정해 분석하고 `analysis-output/소유자-저장소-SHA.json`에 저장합니다. `--sha`에 40자리 커밋 SHA를 넣으면 해당 커밋을 분석합니다. 이 명령은 DB에 연결하거나 분석 결과를 DB에 저장하지 않습니다.

JSON에는 커밋 SHA, 상태, 통계, 경고, 파일·폴더, 심볼, import, SQL 스키마 정보가 들어 있습니다. 소스코드 본문, 설정값, 비밀번호는 저장하지 않습니다. `partial`은 파일 파싱 실패, 미해결 import, 분석하지 않은 심볼릭 링크 등이 있다는 뜻입니다.

Python·JS·JSX·TS·TSX의 정적 선언과 import, PostgreSQL `CREATE TABLE`을 지원합니다. 동적 import, 별칭 경로, 실행 결과, ORM으로만 정의된 스키마 등은 완전히 해석할 수 없습니다. 심볼릭 링크는 경로만 기록하며 따라가지 않습니다.

선택 환경 변수는 `GITHUB_TOKEN`(공개 API 호출 제한 완화), `MAX_ARCHIVE_BYTES`, `MAX_EXTRACTED_BYTES`, `MAX_FILES`, `MAX_SOURCE_FILE_BYTES`, `ANALYSIS_TIMEOUT_SECONDS`입니다. 기본값은 각각 ZIP 512 MiB, 압축 해제 2 GiB, 파일 100,000개, 개별 분석 파일 1 MiB, 900초이며 제한은 양의 정수로 지정합니다. 더 큰 저장소는 환경 변수로 조정하되 디스크·메모리·실행 시간 여유를 먼저 확인합니다. 토큰은 Git이나 결과 JSON에 기록하지 않습니다.

## DB 작업 처리

[DB 설치 및 migration](DATABASE_OPERATIONS.md)을 먼저 완료하고 동일한 `DATABASE_URL`을 Worker에 설정합니다. 아래 명령은 저장소 루트에서 실행합니다.

```bash
# 대기 중인 작업을 계속 처리
uv run --no-dev python -m worker.main

# 작업을 최대 하나만 처리한 뒤 종료
uv run --no-dev python -m worker.main --once
```

백엔드는 `repositories`에 공개 저장소의 정규 URL·소유자·이름·기본 브랜치를 저장하고, `analysis_runs`에 해당 `repository_id`, 고정된 40자리 `commit_sha`, `status='queued'`를 등록해야 합니다. 현재 저장소에는 이를 제공할 FastAPI 엔드포인트가 아직 없습니다. 같은 SHA의 진행 중·완료 작업 중복은 DB 인덱스가 막으며, 재사용 판단은 백엔드가 담당합니다.

Worker는 `queued → fetching → parsing → resolving → completed/partial/failed` 상태를 갱신하고 결과를 하나의 트랜잭션으로 저장합니다. 기본 heartbeat는 5초, 중단 판단은 45초이며 작업당 최대 두 번 점유합니다. `--poll-seconds`, `--stale-seconds`로 조회 주기와 중단 판단 시간을 조정할 수 있습니다. `--once`는 작업 실패 시 종료 코드 1을 반환합니다.

운영에서는 Worker를 별도 비특권 계정 또는 컨테이너로 실행하고, 읽기 전용 루트 파일 시스템, 쓰기 가능한 임시 디렉터리, CPU·메모리·PID 제한을 설정합니다. 네트워크는 GitHub 공식 API와 codeload로 제한하고 사설·메타데이터 주소를 차단해야 합니다. 코드의 DNS 검사와 시간 제한만으로 컨테이너 격리와 네트워크 정책이 구성되지는 않습니다.

실제 GitHub와 테스트 DB를 사용하는 통합 검증은 다음과 같이 실행합니다. DB 테스트는 지정한 테스트 DB에 임시 스키마를 생성하고 종료 후 삭제합니다.

```bash
export TEST_DATABASE_URL='postgresql+psycopg://repoatlas:비밀번호@localhost:5432/repoatlas_test'
export REPOATLAS_LIVE_TESTS=1
uv run pytest worker/tests/test_live_github.py
```

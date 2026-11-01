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

선택 환경 변수는 `GITHUB_TOKEN`(공개 API 호출 제한 완화), `MAX_ARCHIVE_BYTES`, `MAX_EXTRACTED_BYTES`, `MAX_FILES`, `MAX_SOURCE_FILE_BYTES`, `ANALYSIS_TIMEOUT_SECONDS`입니다. 기본값은 각각 50 MiB, 250 MiB, 10,000개, 1 MiB, 180초이며 제한은 양의 정수로 지정합니다. 토큰은 Git이나 결과 JSON에 기록하지 않습니다.

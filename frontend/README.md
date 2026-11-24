# RepoAtlas frontend

React·TypeScript·Vite 프론트엔드입니다. `docs/API_SPEC.md`와 GitHub `develop`의 실제 라우터 구현을 함께 확인해 연결합니다. 백엔드·Worker·DB·배포 코드는 변경하지 않았습니다.

## 실제 백엔드에 연결

프론트 폴더에서 백엔드 담당자가 제공한 주소를 설정합니다. 아래 localhost 주소는 로컬 FastAPI 예시이며 운영 서버 주소가 아닙니다.

```powershell
cd C:\Users\teuri\RepoAtlas-develop\frontend
$env:VITE_API_PROXY_TARGET='http://127.0.0.1:8000'
pnpm dev:backend
```

`dev:backend`는 `.env.backend`를 읽어 real 모드로 실행합니다. 브라우저의 `/api`와 `/openapi.json` 요청을 해당 백엔드 origin으로 프록시합니다. 별도로 저장하려면 `.env.backend.local`에 `VITE_API_PROXY_TARGET=http://제공받은서버:포트`를 넣고 Vite를 재시작합니다. 서버 주소를 받기 전에는 실제 연동을 완료할 수 없습니다.

접속만 확인하는 명령입니다. 저장소 등록·분석 작업을 생성하지 않습니다.

실제 API 모드의 배포 파일은 `pnpm build:backend`로 생성합니다. 기본 `pnpm build`는 mock 모드를 유지합니다.

```powershell
pnpm check:backend http://127.0.0.1:8000/api/v1
```

운영에서 같은 출처의 `/api/v1`·`/openapi.json`을 백엔드로 프록시하면 브라우저 CORS 설정이 필요하지 않습니다. Vite 프록시는 정적 빌드 결과에 포함되지 않으므로 배포 담당자가 운영 프록시를 설정해야 합니다. 별도 origin을 직접 사용하려면 `VITE_API_BASE_URL=https://api.example.com/api/v1`과 서버의 CORS·HTTPS 설정이 필요합니다. 스키마가 기본 위치에 없으면 `VITE_API_SCHEMA_URL`로 전체 OpenAPI URL을 지정합니다. `VITE_*` 값은 공개되므로 토큰·비밀번호를 넣지 않습니다.

## 현재 GitHub 백엔드에 맞춘 동작

확인 기준은 [develop 8fe1e4d](https://github.com/Toc-mentoring/RepoAtlas/tree/8fe1e4d4225e73cf4ee8aad935988b778b80913d/backend/app)입니다.

- `/openapi.json`의 요청 본문·cursor 파라미터를 읽어 지원 기능을 확인합니다. 스키마 조회 실패 시 분석 버튼을 비활성화하고 재시도를 표시합니다.
- 최신 백엔드는 지정 커밋 SHA를 받고, 저장소 목록과 분석 이력을 cursor로 페이지 조회합니다. 프론트는 요청한 SHA와 응답 SHA가 일치하는지 확인합니다.
- 이전 서버는 지원 기능에 따라 기본 브랜치 HEAD 분석과 최대 100개 목록 조회를 사용합니다.
- queued/fetching 등 진행 중 `stats={}` 응답을 허용하며 빠진 통계 항목은 화면에서 0으로 보완합니다. 분석 상태 자체는 변경하지 않습니다.
- 상태는 2초 폴링하며 completed/partial/failed 또는 통신 오류에서 중단합니다. 재시도로 복구할 수 있습니다.
- 결과·검색·다이어그램 API의 cursor, 숫자 file_id, GraphDTO·SHA 원본 링크를 사용합니다.
- 실제 API 오류 시 mock으로 자동 전환하지 않습니다. 쓰기 자동 재시도 없이 request_id·Retry-After·20초 타임아웃을 처리합니다.

실제 서버가 이 소스보다 새 버전일 수 있으므로 API 주소를 받은 뒤 실제 스키마·응답·Worker 진행을 확인해야 합니다.

## 화면 기능

- directory/dependency/symbols 및 경로·깊이·언어·최대 노드 필터
- 아키텍처·ERD 탐색과 최대 노드 필터
- 파일 선택 기반 심볼, 분석 전체 파일·심볼 검색과 결과 이동·선택 강조
- 노드 검색·종류 필터, 관계 근거·SHA가 고정된 GitHub 원본 링크
- 로딩·빈 결과·부분 완료·부분 지원·미지원 사유·잘림·오류 구분
- 모바일 탐색기/그래프/상세 전환, 접을 수 있는 검색·범위 필터

노드 기본 150·최대 300, 깊이 1~8입니다. 파일 선택 목록에 없는 깊은 파일은 전체 검색으로 찾습니다. 검색 대상이 서버의 300개 제한에도 포함되지 않으면 누락 사실을 알립니다.

## mock 및 검증

```powershell
pnpm install --frozen-lockfile
pnpm dev
pnpm test
pnpm build
```

환경 변수를 별도로 설정하지 않은 `pnpm dev`는 브라우저에 저장되는 mock 모드입니다. 실제 저장소를 수집하지 않습니다.

GitHub 현재 구현을 재현한 **프론트 검증용 HTTP 서버**는 다음처럼 사용합니다. 실제 Backend·Worker의 실행·분석 결과를 검증하는 서버는 아닙니다.

```powershell
# 터미널 1 (frontend 폴더)
node tests/contract-server.mjs

# 터미널 2 (frontend 폴더)
$env:VITE_API_PROXY_TARGET='http://127.0.0.1:18080'
pnpm dev:backend --port 15173 --strictPort
```

검증 서버의 기본 모드는 지정 SHA, cursor 페이지네이션, 5종 다이어그램을 제공합니다. 이전 계약을 검증하려면 터미널 1에서 `$env:FIXTURE_API_CONTRACT='legacy'`를 설정한 뒤 서버를 실행합니다.

큰 ERD의 잘림과 최대 노드 조절은 검증 서버를 띄운 뒤 PowerShell에서 아래 명령으로 확인합니다. ERD를 열고 그래프 범위·필터에서 최대 노드를 300으로 설정하면 기본 한도에서 제외된 테이블이 표시됩니다.

```powershell
Invoke-RestMethod 'http://127.0.0.1:18080/__fixture?mode=large-erd'
```

검증 기록과 실제 서버에서 남은 항목은 [INTEGRATION_CHECKLIST.md](INTEGRATION_CHECKLIST.md)에 있습니다.

# 실제 API 연동 인계

기준: `docs/API_SPEC.md`. 프론트엔드만 변경했으며 Backend·Worker·DB·배포 설정은 수정하지 않았다.

## GitHub 실제 구현 반영 (2026-11-17)

- 확인 기준: `Toc-mentoring/RepoAtlas`의 `develop` 커밋 `02604366b003f629d934eee1b515ba8de4e97771`. API 기능 브랜치는 develop보다 앞선 변경이 없었다.
- 현재 `POST /api/v1/repositories/{repo_id}/analyses`는 요청 본문을 받지 않는다. 서버가 기본 브랜치 HEAD를 분석한다. 프론트는 이 서버에서 SHA 입력을 숨기고 본문 없이 요청한다.
- `/openapi.json`으로 지정 SHA 요청 스키마·목록 cursor 지원을 확인한다. 향후 구현되면 해당 UI를 활성화한다. 스키마 오류 시 분석 요청을 막고 재시도를 안내한다.
- 현재 저장소·분석 이력 API는 limit만 받고 next_cursor=null을 반환한다. 최근 최대 100개와 한계 안내를 표시한다. 파일·심볼·검색 API의 cursor는 구현되어 있다.
- `GET /api/v1/analyses/{run_id}`의 진행 중 `stats={}`를 정상 응답으로 처리한다. 수정 전 재현 테스트 실패 → 수정 후 통과했다.
- 테스트 31개 통과. 현재 구현을 재현한 HTTP 검증 서버에서 HEAD 요청 → 빈 통계 진행 상태 → 부분 완료 → directory 150개 노드 표시를 브라우저에서 확인했다. 실제 Backend·DB·Worker를 실행한 검증은 아니다.
- 실제 API 서버 주소는 아직 제공되지 않아 운영 서버 접속·외부 배포 검증은 대기 중이다.
- 실제 서버는 `pnpm check:backend <서버주소/api/v1>`로 읽기 접속을 점검하고, `VITE_API_PROXY_TARGET=<서버 origin>` 설정 후 `pnpm dev:backend`로 연결한다.

## 개발 서버에서 받을 정보

- 접속 가능한 백엔드 origin(프로토콜·호스트·포트)과 `/api/v1` 경로
- 프론트와 같은 출처로 프록시할지, 별도 origin으로 직접 요청할지
- 별도 origin이면 프론트 origin에 대한 CORS 허용 및 `Retry-After` 헤더 노출 여부
- 지정 SHA 요청 지원, DB 마이그레이션 및 Worker 실행 여부

발표 자료에는 EC2·Apache 설치와 열린 포트가 나온다. 이는 FastAPI 배포·Worker 연결·실제 API 주소·HTTPS·CORS가 준비됐음을 뜻하지 않는다. 서버 주소를 추정해 설정하지 않았다.

## 현재 검증 결과 (2026-11-15)

**실제 백엔드 서버 검증은 대기 중이다.** 아래 브라우저 결과는 `tests/contract-server.mjs`의 명세 기반 응답을 프론트의 **real HTTP 요청 경로**로 연결한 결과다. 실제 저장소를 수집하거나 Worker 분석 정확도를 검증한 결과가 아니다.

- 자동 테스트 24개: 기존 mock·UI와 real HTTP 클라이언트·페이지네이션·전체 검색 테스트 통과
- TypeScript 검사와 프로덕션 빌드 통과. 번들 크기와 일부 의존성의 `use client` 지시문 경고가 있다.
- 브라우저: URL·SHA 입력 → 등록 → 분석 요청 → 상태 갱신 → 부분 완료·경고 표시
- directory 150개·300개 노드 렌더링, 잘림 안내와 범위·최대 노드 필터 적용
- dependency 표시·부분 지원 표시·언어 필터·빈 결과 메시지
- 전체 검색에서 현재 그래프 밖의 심볼 선택 → 해당 파일의 symbols 그래프로 이동 → 선택 강조
- SHA가 포함된 GitHub permalink를 새 탭으로 열어 해당 파일 URL로 이동
- 저장소 20 → 40 → 45개 누적, 분석 이력 20 → 40개 누적
- 390px 모바일: 등록·분석 흐름, 탐색기·그래프·상세 전환, 가로 넘침 없음
- API 502 시 오류·문의 ID·재시도 표시, 빈 결과와 구분, mock 자동 전환 없음

## 실제 서버 연결 후 확인할 항목

- [ ] API 주소 설정 후 `/healthz` 및 `/api/v1/repositories` 접근 확인
- [ ] 공개 저장소 URL·실제 존재하는 40자리 SHA로 등록·분석 요청
- [ ] 응답 SHA가 입력과 일치하고, 새 작업 202·중복 재사용 200 동작 확인
- [ ] Worker 상태가 queued → fetching → parsing → resolving → completed/partial로 진행
- [ ] 완료·부분 완료·실패에서 상태 폴링 중단, 통신 실패 시 재시도로 복구
- [ ] 실제 파일 구조·import·심볼과 3종 그래프의 결과 대조
- [ ] 심볼 파일 선택 및 전체 검색 결과가 현재 그래프 밖에서도 이동·강조됨
- [ ] 검색·파일·저장소·분석 이력의 cursor가 실제 서버에서 이어짐
- [ ] 원본 링크가 분석 SHA·파일·라인과 일치
- [ ] 실패·재시도·동시 요청·캐시 재사용 결과를 UI에서 확인
- [ ] 404/409/422/429/502 및 Retry-After·request_id 표시 확인
- [ ] 실제 대형 저장소의 150/300 노드·잘림·범위 좁히기·모바일 조작 확인

## 백엔드 계약 차이의 프론트 처리

- 지정 SHA를 지원하는 서버에서 입력 SHA와 응답 SHA가 다르면 성공 화면으로 이동하지 않고 `COMMIT_SHA_MISMATCH`를 알린다. 현재 HEAD 서버에서는 임의 SHA를 전송하거나 성공한 것처럼 가장하지 않는다.
- `symbols` 생성에는 숫자 `options.file_id`만 전송한다. 심볼 검색 결과의 파일 ID는 A07의 정확한 파일 경로로 찾으며 cursor를 따라 조회한다.
- 그래프에 허용되지 않은 필터를 보내지 않는다. directory: root_path/depth/max_nodes, dependency: 여기에 language, symbols: file_id/max_nodes.
- `truncated`/`has_more` 시 범위를 줄인다. 최대 300개 제한 때문에 검색 대상이 새 그래프에도 없으면 누락 사실을 알린다. 특정 심볼의 그래프 내 포함을 보장하려면 서버의 추가 범위 지정 계약이 필요하다.
- 쓰기 요청은 자동 재시도하지 않는다. 타임아웃 시 서버가 처리했을 수 있다는 안내를 표시한다.
- 429의 Retry-After가 제공되면 해당 시각 전에는 추가 HTTP 요청을 보내지 않는다. 별도 origin에서는 이 헤더를 읽을 수 있도록 서버가 노출해야 한다.
- 원본 링크는 API가 제공한 HTTPS GitHub 주소 중 40자리 SHA permalink만 표시한다. mock 모드에서는 링크를 제공하지 않는다.

# RepoAtlas frontend

React·TypeScript·Vite 기반 프론트엔드입니다. 기본값은 브라우저에 저장되는 예시 데이터이며 실제 저장소를 수집하지 않습니다.

## 실행 및 검증

Node.js와 pnpm을 설치한 후 `frontend/`에서 실행합니다.

```bash
pnpm install --frozen-lockfile
pnpm dev
pnpm test
pnpm build
```

서버가 출력한 로컬 주소에서 확인합니다. 기본 mock은 localStorage에 저장되므로 브라우저마다 데이터가 독립적입니다. 개발자 도구에서 `repoatlas.mock.v2`와 `repoatlas.mock.graphs.v1`을 지우면 예시 데이터를 초기화할 수 있습니다. 샘플 저장소에서 완료·부분 완료·실패 상태를 확인할 수 있습니다.

## API 전환

기본 모드는 mock입니다. 실제 백엔드가 준비된 경우 아래 환경 변수로 전환합니다.

```bash
VITE_API_MODE=real pnpm dev
```

PowerShell에서는 `$env:VITE_API_MODE='real'; pnpm dev`를 사용합니다. 개발 서버는 `/api` 요청을 `http://127.0.0.1:8000`으로 프록시합니다. 운영에서는 같은 출처의 `/api/v1`을 백엔드에 연결하고 SPA 경로에 `index.html`을 제공해야 합니다. 실제 API 연동은 백엔드 준비 후 검증해야 합니다.

## 현재 범위

- 저장소 등록·목록·상세, 분석 요청·이력·상태와 종료 상태까지 2초 폴링
- 다이어그램 지원 유형 조회, 옵션 선택, GraphDTO 생성·재조회, React Flow·Dagre 렌더링
- 폴더 탐색, 예시 파일 심볼 보기, 검색, 확대·축소, 선택, 경고와 미지원 사유 표시
- mock GraphDTO의 경로와 SHA는 가상입니다. 실제 원본 링크는 실제 API가 반환한 경우에만 표시합니다.

## 남은 통합 작업

실제 API와 스키마·오류·페이지네이션 통합 검증, 서버 검색 및 파일·심볼 조회, 필터 선택 개선, 실제 원본 링크와 대형 그래프 및 모바일 동작 검증이 필요합니다. 아키텍처와 ERD는 예시 데이터에 근거가 없어 미지원으로 표시합니다. 저장소에 포함된 이전 그래프 시안 `src/App.tsx`는 현재 라우트에서 사용하지 않습니다.

# RepoAtlas frontend

## 실행

Node.js와 pnpm이 필요합니다.

```bash
pnpm install
pnpm dev
```

브라우저에서 표시된 로컬 주소를 엽니다. `pnpm build`로 타입 검사와 프로덕션 빌드를 실행합니다.

현재 저장소와 분석 API는 `src/api/mock.ts`에 구현한 브라우저 전용 mock입니다. 등록 데이터와 분석 이력은 브라우저 localStorage에 보관되며, 실제 GitHub 접근이나 백엔드 호출은 없습니다. 개발자 도구에서 `repoatlas.mock.v2` 항목을 지우면 예시 데이터를 초기화할 수 있습니다. 분석 진행은 약 8초에 걸쳐 모의 실행됩니다. 기본 예시에서 완료, 부분 완료, 실패 화면을 확인할 수 있습니다.

기존 그래프 시안은 `/demo/graph`에서 볼 수 있으며, 분석 API 응답과 연결되지 않은 별도 예시입니다. 백엔드 연동 및 GraphDTO 기반 그래프는 후속 작업입니다.

// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let api: (typeof import("./client"))["api"];
const reply = (data: unknown, status = 200, headers?: HeadersInit) =>
  new Response(JSON.stringify(data), { status, headers });
const fetchMock = vi.fn();
beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("VITE_API_MODE", "real");
  vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/api/v1");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  api = (await import("./client")).api;
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

it("지정 SHA와 서버 주소를 사용하고 202/200 캐시 응답을 처리한다", async () => {
  const data = {
    run_id: "run",
    repository_id: "repo",
    commit_sha: "a".repeat(40),
    status: "queued",
    reused: false,
    status_url: "/api/v1/analyses/run",
  };
  fetchMock
    .mockResolvedValueOnce(reply(data, 202))
    .mockResolvedValueOnce(reply({ ...data, reused: true }));
  expect((await api.startAnalysis("repo", "A".repeat(40))).reused).toBe(false);
  expect((await api.startAnalysis("repo", "a".repeat(40))).reused).toBe(true);
  expect(fetchMock).toHaveBeenCalledWith(
    "https://api.example.test/api/v1/repositories/repo/analyses",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ commit_sha: "a".repeat(40) }),
    }),
  );
});
it("서버가 입력 SHA를 무시하면 성공으로 표시하지 않는다", async () => {
  fetchMock.mockResolvedValue(
    reply({ run_id: "run", commit_sha: "b".repeat(40), status: "queued" }, 202),
  );
  await expect(api.startAnalysis("repo", "a".repeat(40))).rejects.toMatchObject(
    { error: { code: "COMMIT_SHA_MISMATCH" } },
  );
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("불투명 cursor를 인코딩해서 목록과 이력을 추가 조회한다", async () => {
  fetchMock.mockImplementation(async () =>
    reply({ items: [], next_cursor: null }),
  );
  await api.listRepositories({ cursor: "next/+=" });
  await api.listAnalyses("repo", { cursor: "run/+=" });
  expect(fetchMock.mock.calls[0][0]).toContain("cursor=next%2F%2B%3D");
  expect(fetchMock.mock.calls[1][0]).toContain("cursor=run%2F%2B%3D");
});
it("네트워크 오류 시 mock을 반환하거나 POST를 자동 재시도하지 않는다", async () => {
  fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
  await expect(
    api.createRepository("https://github.com/acme/demo"),
  ).rejects.toMatchObject({ error: { code: "NETWORK_ERROR" } });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("프록시의 HTML 오류와 비정상 200 응답도 화면 오류로 변환한다", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response("<html>Bad gateway</html>", { status: 502 }),
    )
    .mockResolvedValueOnce(reply({ unexpected: true }));
  await expect(api.listRepositories()).rejects.toMatchObject({
    status: 502,
    error: { code: "HTTP_ERROR" },
  });
  await expect(api.listRepositories()).rejects.toMatchObject({
    error: { code: "INVALID_RESPONSE" },
  });
});
it("429의 Retry-After와 request_id를 보존하고 대기 중 재요청을 막는다", async () => {
  vi.useFakeTimers();
  fetchMock.mockResolvedValue(
    reply(
      {
        error: {
          code: "RATE_LIMITED",
          message: "호출 제한",
          details: {},
          request_id: "req-1",
        },
      },
      429,
      { "Retry-After": "10" },
    ),
  );
  await expect(api.listRepositories()).rejects.toMatchObject({
    error: { request_id: "req-1" },
    retryAt: Date.now() + 10000,
  });
  await expect(api.listRepositories()).rejects.toMatchObject({ status: 429 });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(10001);
  await expect(api.listRepositories()).rejects.toMatchObject({ status: 429 });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
it("응답이 없는 요청을 중단하고 재요청을 자동 실행하지 않는다", async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(
    (_url, { signal }) =>
      new Promise((_resolve, reject) =>
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        ),
      ),
  );
  const result = expect(api.getAnalysis("run")).rejects.toMatchObject({
    error: { code: "REQUEST_TIMEOUT" },
  });
  await vi.advanceTimersByTimeAsync(20001);
  await result;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("현재 백엔드의 queued 빈 통계 응답을 정상 상태로 읽는다", async () => {
  fetchMock.mockResolvedValue(
    reply({
      id: "run",
      repository_id: "repo",
      commit_sha: "a".repeat(40),
      status: "queued",
      progress: 0,
      stats: {},
      warnings: [],
      error_code: null,
      error_message: null,
      created_at: "2026-11-17T00:00:00Z",
      finished_at: null,
    }),
  );
  const run = await api.getAnalysis("run");
  expect(run.status).toBe("queued");
  expect(run.stats.file_count).toBe(0);
});
it("HEAD 분석은 본문과 SHA를 보내지 않고 서버가 고정한 SHA를 사용한다", async () => {
  fetchMock.mockResolvedValue(
    reply(
      {
        run_id: "run",
        repository_id: "repo",
        commit_sha: "b".repeat(40),
        status: "queued",
        reused: false,
        status_url: "/api/v1/analyses/run",
      },
      202,
    ),
  );
  const result = await api.startAnalysis("repo");
  expect(result.commit_sha).toBe("b".repeat(40));
  const options = fetchMock.mock.calls[0][1];
  expect(options.method).toBe("POST");
  expect(options.body).toBeUndefined();
});
it("원격 API와 같은 origin의 OpenAPI를 조회한다", async () => {
  const { currentSchema } = await import("../../tests/fixtures/backendSchema");
  fetchMock.mockResolvedValue(reply(currentSchema));
  expect((await api.getCapabilities()).commitSha).toBe(false);
  expect(fetchMock.mock.calls[0][0]).toBe(
    "https://api.example.test/openapi.json",
  );
});
it("존재하지 않는 노드를 연결하는 잘못된 그래프를 거부한다", async () => {
  fetchMock.mockResolvedValue(
    reply({
      diagram_id: "g",
      run_id: "r",
      type: "dependency",
      availability: "available",
      nodes: [],
      edges: [
        {
          id: "e",
          source: "missing",
          target: "also-missing",
          data: { evidence: [] },
        },
      ],
      warnings: [],
      truncated: false,
      has_more: false,
    }),
  );
  await expect(api.getDiagram("g")).rejects.toMatchObject({
    error: { code: "INVALID_RESPONSE" },
  });
});

it.each([
  ["directory", "dir:1", "directory", "file:2", "file"],
  ["symbols", "file:2", "file", "symbol:3", "function"],
] as const)(
  "%s에서 별도 근거가 없는 포함 관계를 읽는다",
  async (type, source, sourceType, target, targetType) => {
    const graph = {
      diagram_id: "g",
      run_id: "r",
      type,
      availability: "available",
      nodes: [
        { id: source, type: sourceType, label: source, data: {} },
        { id: target, type: targetType, label: target, data: {} },
      ],
      edges: [{ id: "e", type: "contains", source, target, data: {} }],
      warnings: [],
      truncated: false,
      has_more: false,
      unresolved_references: 0,
    };
    fetchMock
      .mockResolvedValueOnce(reply(graph, 201))
      .mockResolvedValueOnce(reply(graph));
    await expect(api.createDiagram("r", type, {})).resolves.toEqual(graph);
    await expect(api.getDiagram("g")).resolves.toEqual(graph);
  },
);

it("ERD에서 컬럼 포함 관계와 원본 경로가 없는 외래 키 근거를 읽는다", async () => {
  const graph = {
    diagram_id: "g",
    run_id: "r",
    type: "erd",
    availability: "available",
    nodes: [
      {
        id: "table:1",
        type: "table",
        label: "tasks",
        data: { schema: "public", path: null, github_url: null },
      },
      {
        id: "column:2",
        type: "column",
        label: "id",
        data: { data_type: "bigint", is_primary: true },
      },
      {
        id: "column:3",
        type: "column",
        label: "parent_id",
        data: { data_type: "bigint" },
      },
    ],
    edges: [
      {
        id: "contains:2",
        type: "contains",
        source: "table:1",
        target: "column:2",
        data: {},
      },
      {
        id: "contains:3",
        type: "contains",
        source: "table:1",
        target: "column:3",
        data: {},
      },
      {
        id: "foreign_key:1",
        type: "foreign_key",
        source: "column:3",
        target: "column:2",
        data: {
          certainty: "confirmed",
          evidence: [{ path: null, github_url: null, basis: "sql_ddl" }],
        },
      },
    ],
    warnings: [],
    truncated: false,
    has_more: false,
    unresolved_references: 0,
  };
  fetchMock.mockResolvedValue(reply(graph));
  await expect(api.getDiagram("g")).resolves.toEqual(graph);
});

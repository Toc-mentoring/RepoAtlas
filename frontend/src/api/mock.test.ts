// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { mockApi, ApiError } from "./mock";
import { catalog, createGraph, getGraph } from "./mockGraph";
beforeEach(() => localStorage.clear());
describe("mock API 계약", () => {
  it("등록과 중복 등록은 같은 UUID를 반환하며 명세 형태를 유지한다", async () => {
    const a = await mockApi.createRepository("https://github.com/acme/project");
    const b = await mockApi.createRepository("https://github.com/acme/project");
    expect(a.is_existing).toBe(false);
    expect(b.is_existing).toBe(true);
    expect(b.id).toBe(a.id);
    expect(a.id).toMatch(/^[\da-f-]{36}$/);
    expect(a.canonical_url).toBe("https://github.com/acme/project");
    expect((await mockApi.listRepositories()).next_cursor).toBeNull();
  });
  it("잘못된 URL은 422와 공통 오류 형식을 반환한다", async () => {
    try {
      await mockApi.createRepository("https://example.com/x/y");
      throw Error("expected rejection");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const error = e as ApiError;
      expect(error.status).toBe(422);
      expect(error.error.code).toBe("INVALID_REPOSITORY_URL");
      expect(error.error.request_id).toBeTruthy();
    }
  });
  it("부분 완료는 다이어그램 조회 가능하고 실패는 차단한다", async () => {
    const list = await mockApi.listRepositories();
    const partial = list.items.find((x) => x.name === "next.js")!;
    const failed = list.items.find((x) => x.name === "api-server")!;
    expect(
      (await catalog(partial.latest_run_id!)).items.find(
        (x) => x.type === "erd",
      )?.availability,
    ).toBe("unsupported");
    await expect(catalog(failed.latest_run_id!)).rejects.toMatchObject({
      status: 409,
      error: { code: "ANALYSIS_NOT_READY" },
    });
  });
  it("GraphDTO 관계는 반환된 노드만 참조하고 제한·경고와 재조회를 보존한다", async () => {
    const list = await mockApi.listRepositories();
    const run = list.items.find((x) => x.name === "next.js")!.latest_run_id!;
    const graph = await createGraph(run, "dependency", {
      root_path: "src",
      depth: 2,
      max_nodes: 20,
    });
    const ids = new Set(graph.nodes.map((n) => n.id));
    expect(
      graph.edges.every((e) => ids.has(e.source) && ids.has(e.target)),
    ).toBe(true);
    expect(graph.warnings.length).toBeGreaterThan(0);
    expect((await getGraph(graph.diagram_id)).diagram_id).toBe(
      graph.diagram_id,
    );
    await expect(createGraph(run, "symbols", {})).rejects.toMatchObject({
      status: 422,
      error: { code: "INVALID_FILTER" },
    });
  });
  it("폴더 깊이 제한은 직계 자식만 포함한다", async () => {
    const list = await mockApi.listRepositories();
    const run = list.items[0].latest_run_id!;
    const graph = await createGraph(run, "directory", {
      root_path: ".",
      depth: 1,
      max_nodes: 20,
    });
    expect(graph.nodes.map((n) => n.id)).toEqual(["dir:.", "dir:src"]);
    expect(graph.edges).toHaveLength(1);
  });
});

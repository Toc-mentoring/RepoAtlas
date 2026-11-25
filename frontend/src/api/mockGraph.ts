import { mockApi, ApiError } from "./mock";
import { architectureExample, erdExample } from "./mockSpecialDiagrams";
import type { Catalog, DiagramOptions, DiagramType, GraphDTO } from "./types";
const key = "repoatlas.mock.graphs.v1";
const delay = () => new Promise<void>((r) => setTimeout(r, 250));
const fail = (status: number, code: string, message: string): never => {
  throw new ApiError(status, {
    code,
    message,
    details: {},
    request_id: `mock-${crypto.randomUUID().slice(0, 8)}`,
  });
};
async function ready(runId: string) {
  const run = await mockApi.getAnalysis(runId);
  if (run.status !== "completed" && run.status !== "partial")
    return fail(
      409,
      "ANALYSIS_NOT_READY",
      "분석 결과가 아직 준비되지 않았습니다.",
    );
  return run;
}
export async function catalog(runId: string): Promise<Catalog> {
  const run = await ready(runId);
  return {
    run_id: runId,
    items: [
      { type: "directory", availability: "available", reason: null },
      { type: "dependency", availability: "available", reason: null },
      { type: "symbols", availability: "available", reason: null },
      {
        type: "architecture",
        availability: run.status === "partial" ? "partial" : "available",
        reason:
          run.status === "partial" ? "일부 설정 파일만 분석했습니다." : null,
      },
      {
        type: "erd",
        availability: run.status === "partial" ? "unsupported" : "available",
        reason:
          run.status === "partial"
            ? "이 예시에는 해석 가능한 SQL DDL이 없습니다."
            : null,
      },
    ],
  };
}
const sample = [
  { id: 1, name: "main.tsx", path: "src/main.tsx", language: "typescript" },
  { id: 2, name: "App.tsx", path: "src/App.tsx", language: "typescript" },
  { id: 3, name: "utils.ts", path: "src/utils.ts", language: "typescript" },
  {
    id: 4,
    name: "Header.tsx",
    path: "src/components/Header.tsx",
    language: "typescript",
  },
  { id: 5, name: "api.ts", path: "src/api.ts", language: "typescript" },
];
export async function createGraph(
  runId: string,
  type: DiagramType,
  options: DiagramOptions,
): Promise<GraphDTO> {
  const run = await ready(runId);
  if (type === "erd" && run.status === "partial")
    return fail(
      409,
      "DIAGRAM_UNSUPPORTED",
      "이 다이어그램에 필요한 근거가 없습니다.",
    );
  if (type === "symbols" && !sample.some((x) => x.id === options.file_id))
    return fail(
      422,
      "INVALID_FILTER",
      "심볼 그래프에는 유효한 파일을 선택해야 합니다.",
    );
  if (
    (options.depth !== undefined && (options.depth < 1 || options.depth > 8)) ||
    (options.max_nodes !== undefined &&
      (options.max_nodes < 20 || options.max_nodes > 300)) ||
    options.root_path?.split("/").includes("..")
  )
    return fail(422, "INVALID_FILTER", "필터 값을 확인해 주세요.");
  const root = options.root_path || ".";
  if (root !== "." && root !== "src" && root !== "src/components")
    return fail(404, "INVALID_PATH", "경로를 찾을 수 없습니다.");
  const files = sample.filter(
    (f) =>
      (root === "." || f.path.startsWith(root + "/")) &&
      (!options.language || f.language === options.language),
  );
  const n = (
    id: string,
    type: string,
    label: string,
    data: GraphDTO["nodes"][number]["data"],
  ) => ({ id, type, label, data });
  const e = (source: string, target: string, type: string) => ({
    id: `${type}:${source}:${target}`,
    source,
    target,
    type,
    data: {
      certainty: "confirmed" as const,
      evidence: [{ path: "src/main.tsx", line: 1, basis: "mock_fixture" }],
    },
  });
  let nodes: GraphDTO["nodes"] = [],
    edges: GraphDTO["edges"] = [];
  if (type === "directory") {
    const folders =
      root === "src/components"
        ? ["src/components"]
        : root === "src"
          ? ["src", "src/components"]
          : [".", "src", "src/components"];
    nodes = folders.map((p) =>
      n(
        `dir:${p}`,
        "directory",
        p === "." ? "sample-web" : p.split("/").pop()!,
        { path: p },
      ),
    );
    nodes.push(
      ...files.map((f) =>
        n(`file:${f.id}`, "file", f.name, {
          path: f.path,
          language: f.language,
        }),
      ),
    );
    if (root === ".") edges.push(e("dir:.", "dir:src", "contains"));
    if (folders.includes("src/components") && root !== "src/components")
      edges.push(e("dir:src", "dir:src/components", "contains"));
    for (const f of files)
      edges.push(
        e(
          f.path.includes("/components/") ? "dir:src/components" : "dir:src",
          `file:${f.id}`,
          "contains",
        ),
      );
    if (options.depth) {
      const included = new Set([`dir:${root}`]);
      for (let level = 0; level < options.depth; level++) {
        const previous = new Set(included);
        for (const edge of edges) {
          if (previous.has(edge.source)) included.add(edge.target);
        }
      }
      nodes = nodes.filter((x) => included.has(x.id));
      edges = edges.filter(
        (x) => included.has(x.source) && included.has(x.target),
      );
    }
  } else if (type === "dependency") {
    nodes = files.map((f) =>
      n(`file:${f.id}`, "file", f.name, { path: f.path, language: f.language }),
    );
    const ids = new Set(nodes.map((x) => x.id));
    edges = [
      e("file:1", "file:2", "imports"),
      e("file:1", "file:3", "imports"),
      e("file:2", "file:4", "imports"),
      e("file:2", "file:5", "imports"),
    ].filter((x) => ids.has(x.source) && ids.has(x.target));
  } else if (type === "symbols") {
    const file = sample.find((f) => f.id === options.file_id)!;
    nodes = [
      n(`file:${file.id}`, "file", file.name, {
        path: file.path,
        language: file.language,
      }),
      n(
        `symbol:${100 + file.id}`,
        "function",
        file.id === 2 ? "App" : "exampleFunction",
        {
          path: file.path,
          line: 12,
        },
      ),
    ];
    edges = [e(nodes[0].id, nodes[1].id, "declares")];
  } else {
    ({ nodes, edges } =
      type === "architecture" ? architectureExample : erdExample);
  }
  const limit = options.max_nodes ?? 150;
  const truncated = nodes.length > limit;
  if (truncated) {
    nodes = nodes.slice(0, limit);
    const ids = new Set(nodes.map((x) => x.id));
    edges = edges.filter((x) => ids.has(x.source) && ids.has(x.target));
  }
  const graph: GraphDTO = {
    diagram_id: crypto.randomUUID(),
    run_id: runId,
    type,
    availability:
      type === "architecture" && run.status === "partial"
        ? "partial"
        : "available",
    truncated,
    has_more: truncated,
    nodes,
    edges,
    warnings: [
      ...(run.status === "partial" ? run.warnings : []),
      ...(truncated ? ["노드가 제한되어 범위를 좁혀 주세요."] : []),
    ],
    unresolved_references: type === "dependency" ? 1 : 0,
  };
  const all = JSON.parse(localStorage.getItem(key) || "{}") as Record<
    string,
    GraphDTO
  >;
  all[graph.diagram_id] = graph;
  localStorage.setItem(key, JSON.stringify(all));
  return graph;
}
export async function getGraph(id: string): Promise<GraphDTO> {
  await delay();
  const all = JSON.parse(localStorage.getItem(key) || "{}") as Record<
    string,
    GraphDTO
  >;
  return (
    all[id] ?? fail(404, "DIAGRAM_NOT_FOUND", "다이어그램을 찾을 수 없습니다.")
  );
}

export async function search(runId: string, q: string) {
  await ready(runId);
  if (q.length < 2 || q.length > 100)
    return fail(422, "INVALID_FILTER", "검색어는 2~100자여야 합니다.");
  return {
    items: [
      ...sample
        .filter((f) => f.path.toLowerCase().includes(q.toLowerCase()))
        .map((f) => ({
          kind: "file" as const,
          id: `file:${f.id}`,
          label: f.path,
          path: f.path,
          line: null,
        })),
      ...sample
        .filter((f) =>
          `${f.path} ${f.id === 2 ? "App" : "exampleFunction"}`
            .toLowerCase()
            .includes(q.toLowerCase()),
        )
        .map((f) => ({
          kind: "symbol" as const,
          id: `symbol:${100 + f.id}`,
          label: f.id === 2 ? "App" : "exampleFunction",
          path: f.path,
          line: 12,
        })),
    ],
    next_cursor: null,
  };
}

export async function mockSymbols(runId: string, fileId: number) {
  await ready(runId);
  const file = sample.find((f) => f.id === fileId);
  return {
    items: file
      ? [
          {
            id: 100 + file.id,
            file_id: file.id,
            name: file.id === 2 ? "App" : "exampleFunction",
            kind: "function",
            start_line: 12,
            end_line: 18,
            github_url: "",
          },
        ]
      : [],
    next_cursor: null,
  };
}

// Frontend browser-test fixture only. Does not run Worker, access a DB, or fetch GitHub.
// Run: node tests/contract-server.mjs (127.0.0.1:18080).
import http from "node:http";
import { randomUUID } from "node:crypto";
const planned = process.env.FIXTURE_API_CONTRACT === "planned";
const sha = "02604366b003f629d934eee1b515ba8de4e97771";
const repoId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const date = "2026-11-15T01:00:00Z";
const repos = Array.from({ length: 45 }, (_, i) => ({
  id: i ? `repo-${i}` : repoId,
  provider: "github",
  owner: "Toc-mentoring",
  name: i ? `fixture-${i}` : "RepoAtlas",
  canonical_url: "https://github.com/Toc-mentoring/RepoAtlas",
  default_branch: "develop",
  latest_run_id: runId,
  created_at: date,
}));
const stats = {
  file_count: 342,
  parsed_files: 341,
  symbols: 341,
  resolved_imports: 340,
  unresolved_imports: 1,
  tables: 0,
};
const runs = new Map([
  [
    runId,
    {
      id: runId,
      repository_id: repoId,
      commit_sha: sha,
      status: "partial",
      progress: 100,
      stats,
      warnings: ["검증용 응답: 일부 import를 해석하지 못했습니다."],
      error_code: null,
      error_message: null,
      created_at: date,
      finished_at: date,
    },
  ],
]);
const history = Array.from({ length: 45 }, (_, i) => ({
  ...runs.get(runId),
  id: i ? `history-${i}` : runId,
}));
const files = Array.from({ length: 340 }, (_, i) => ({
  id: i + 10,
  parent_id: 2,
  kind: "file",
  path: `src/file-${String(i).padStart(3, "0")}.ts`,
  name: `file-${String(i).padStart(3, "0")}.ts`,
  language: "typescript",
  parse_status: "parsed",
}));
files.push({
  id: 900,
  parent_id: 3,
  kind: "file",
  path: "worker/analyzer.py",
  name: "analyzer.py",
  language: "python",
  parse_status: "parsed",
});
const sourceNodes = [
  {
    id: 1,
    parent_id: null,
    kind: "directory",
    path: ".",
    name: "RepoAtlas",
    language: null,
    parse_status: "not_applicable",
  },
  {
    id: 2,
    parent_id: 1,
    kind: "directory",
    path: "src",
    name: "src",
    language: null,
    parse_status: "not_applicable",
  },
  {
    id: 3,
    parent_id: 1,
    kind: "directory",
    path: "worker",
    name: "worker",
    language: null,
    parse_status: "not_applicable",
  },
  ...files,
];
const graphs = new Map();
const polls = new Map();
let mode = "normal";
function page(items, url) {
  const offset = Number(
    url.searchParams.get("cursor")?.replace("fixture:", "") || 0,
  );
  const limit = Number(url.searchParams.get("limit") || 20);
  return {
    items: items.slice(offset, offset + limit),
    next_cursor:
      offset + limit < items.length ? `fixture:${offset + limit}` : null,
  };
}
const edge = (s, t, type) => ({
  id: `${type}:${s}:${t}`,
  source: s,
  target: t,
  type,
  data: {
    certainty: "confirmed",
    evidence: [
      {
        path: "worker/analyzer.py",
        line: 1,
        basis: "frontend_contract_fixture",
      },
    ],
  },
});
function build(run, type, options) {
  const root = options.root_path || ".";
  const within = (n) =>
    root === "." || n.path === root || n.path.startsWith(root + "/");
  const link = (path) =>
    `https://github.com/Toc-mentoring/RepoAtlas/blob/${run.commit_sha}/${path}`;
  const node = (n) => ({
    id: `${n.kind === "file" ? "file" : "dir"}:${n.id}`,
    type: n.kind,
    label: n.name,
    data: { path: n.path, language: n.language, github_url: link(n.path) },
  });
  let nodes = [],
    edges = [];
  if (type === "symbols") {
    const file = files.find((f) => f.id === options.file_id);
    if (!file) throw Error("파일을 선택해 주세요.");
    nodes = [
      node(file),
      {
        id: `symbol:${file.id + 1000}`,
        type: "function",
        label: "analyze_repository",
        data: { path: file.path, line: 1, github_url: link(file.path) + "#L1" },
      },
    ];
    edges = [edge(nodes[0].id, nodes[1].id, "declares")];
  } else {
    const subset = (type === "directory" ? sourceNodes : files)
      .filter(within)
      .filter((n) => !options.language || n.language === options.language);
    const depth = options.depth || 2;
    const rootDepth = root === "." ? 0 : root.split("/").length;
    nodes = subset
      .filter(
        (n) => n.path === "." || n.path.split("/").length - rootDepth <= depth,
      )
      .map(node);
    const ids = new Set(nodes.map((n) => n.id));
    edges =
      type === "directory"
        ? subset
            .filter((n) => n.parent_id)
            .map((n) =>
              edge(
                `dir:${n.parent_id}`,
                `${n.kind === "file" ? "file" : "dir"}:${n.id}`,
                "contains",
              ),
            )
            .filter((e) => ids.has(e.source) && ids.has(e.target))
        : nodes.slice(1).map((n) => edge(nodes[0].id, n.id, "imports"));
  }
  const max = options.max_nodes || 150,
    truncated = nodes.length > max;
  nodes = nodes.slice(0, max);
  const ids = new Set(nodes.map((n) => n.id));
  edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  return {
    diagram_id: randomUUID(),
    run_id: run.id,
    type,
    availability: type === "dependency" ? "partial" : "available",
    truncated,
    has_more: truncated,
    nodes,
    edges,
    warnings: truncated ? ["노드 표시 한도에 도달했습니다."] : [],
    unresolved_references: type === "dependency" ? 1 : 0,
  };
}
const server = http.createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  const send = (value, status = 200) => {
    res.statusCode = status;
    res.end(JSON.stringify(value));
  };
  const fail = (status, code, message) =>
    send(
      {
        error: { code, message, details: {}, request_id: "fixture-request-1" },
      },
      status,
    );
  const url = new URL(req.url, "http://localhost");
  const p = url.pathname.replace(/^\/api\/v1/, "");
  if (p === "/__fixture") {
    mode = url.searchParams.get("mode") || "normal";
    return send({ mode });
  }
  if (mode === "unavailable")
    return fail(502, "GITHUB_UNAVAILABLE", "검증용 서버 연결 실패");
  if (p === "/openapi.json")
    return send({
      openapi: "3.1.0",
      paths: {
        "/api/v1/repositories": {
          get: { parameters: planned ? [{ in: "query", name: "cursor" }] : [] },
        },
        "/api/v1/repositories/{repo_id}/analyses": {
          get: { parameters: planned ? [{ in: "query", name: "cursor" }] : [] },
          post: planned
            ? {
                requestBody: {
                  content: {
                    "application/json": {
                      schema: {
                        type: "object",
                        properties: { commit_sha: { type: "string" } },
                      },
                    },
                  },
                },
              }
            : {},
        },
      },
    });
  if (p === "/repositories" && req.method === "GET") {
    const result = page(repos, url);
    return send({
      ...result,
      next_cursor: planned ? result.next_cursor : null,
    });
  }
  let body = {};
  if (req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    try {
      body = raw ? JSON.parse(raw) : {};
    } catch {
      return fail(422, "INVALID_FILTER", "잘못된 JSON");
    }
  }
  if (p === "/repositories" && req.method === "POST") {
    if (!/^https:\/\/github\.com\/[^/]+\/[^/]+$/.test(body.url || ""))
      return fail(
        422,
        "INVALID_REPOSITORY_URL",
        "공개 GitHub 저장소 주소를 확인해 주세요.",
      );
    return send({ ...repos[0], is_existing: true }, 200);
  }
  if (/^\/repositories\/[^/]+$/.test(p)) return send(repos[0]);
  if (/^\/repositories\/[^/]+\/analyses$/.test(p)) {
    if (req.method === "GET") {
      const result = page(history, url);
      return send({
        ...result,
        next_cursor: planned ? result.next_cursor : null,
      });
    }
    if (planned && !/^[a-f0-9]{40}$/i.test(body.commit_sha || ""))
      return fail(422, "INVALID_COMMIT_SHA", "SHA를 확인해 주세요.");
    const requestedSha = planned ? body.commit_sha : sha;
    const existing = [...runs.values()].find(
      (r) => r.commit_sha === requestedSha && r.status !== "partial",
    );
    const run = existing || {
      ...runs.get(runId),
      id: randomUUID(),
      commit_sha: requestedSha,
      status: "queued",
      progress: 0,
      stats: {},
      warnings: [],
      finished_at: null,
    };
    runs.set(run.id, run);
    if (!existing) history.unshift(run);
    return send(
      {
        run_id: run.id,
        repository_id: repoId,
        commit_sha: run.commit_sha,
        status: run.status,
        reused: !!existing,
        status_url: `/api/v1/analyses/${run.id}`,
      },
      existing ? 200 : 202,
    );
  }
  const match = p.match(/^\/analyses\/([^/]+)(?:\/(.*))?$/);
  if (match) {
    const run = runs.get(match[1]);
    if (!run)
      return fail(404, "ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다.");
    const action = match[2];
    if (!action) {
      if (run.status !== "partial" && run.status !== "completed") {
        const count = (polls.get(run.id) || 0) + 1;
        polls.set(run.id, count);
        run.status = count < 2 ? "parsing" : "partial";
        run.progress = count < 2 ? 55 : 100;
        run.stats = count < 2 ? {} : stats;
        run.warnings =
          count < 2
            ? []
            : ["검증용 부분 완료: 일부 import가 미해결 상태입니다."];
        run.finished_at = count < 2 ? null : date;
      }
      return send(run);
    }
    if (action === "diagram-types")
      return send({
        run_id: run.id,
        items: [
          "directory",
          "dependency",
          "symbols",
          "architecture",
          "erd",
        ].map((type) => ({
          type,
          availability: ["architecture", "erd"].includes(type)
            ? "unsupported"
            : "available",
          reason: ["architecture", "erd"].includes(type)
            ? "검증용 미지원 사유"
            : null,
        })),
      });
    if (action === "nodes")
      return send(
        page(
          sourceNodes.filter((n) => {
            const root = url.searchParams.get("root_path") || ".";
            return (
              root === "." || n.path === root || n.path.startsWith(root + "/")
            );
          }),
          url,
        ),
      );
    if (action === "symbols") {
      const f =
        files.find((f) => f.id === Number(url.searchParams.get("file_id"))) ||
        files[0];
      return send({
        items: [
          {
            id: f.id + 1000,
            file_id: f.id,
            name: "analyze_repository",
            kind: "function",
            start_line: 1,
            end_line: 5,
            github_url: `https://github.com/Toc-mentoring/RepoAtlas/blob/${run.commit_sha}/${f.path}#L1-L5`,
          },
        ],
        next_cursor: null,
      });
    }
    if (action === "search") {
      const q = (url.searchParams.get("q") || "").toLowerCase();
      const items = files
        .filter((f) => f.path.toLowerCase().includes(q))
        .map((f) => ({
          kind: "file",
          id: `file:${f.id}`,
          label: f.name,
          path: f.path,
          line: null,
        }));
      if ("analyze_repository".includes(q))
        items.push({
          kind: "symbol",
          id: "symbol:1900",
          label: "analyze_repository",
          path: "worker/analyzer.py",
          line: 1,
        });
      return send(page(items, url));
    }
    if (action === "diagrams" && req.method === "POST") {
      if (["architecture", "erd"].includes(body.type))
        return fail(409, "DIAGRAM_UNSUPPORTED", "이 유형은 지원하지 않습니다.");
      try {
        const g = build(run, body.type, body.options || {});
        graphs.set(g.diagram_id, g);
        return send(g, 201);
      } catch (e) {
        return fail(422, "INVALID_FILTER", e.message);
      }
    }
  }
  if (p.startsWith("/diagrams/")) {
    const g = graphs.get(p.split("/").pop());
    return g
      ? send(g)
      : fail(404, "DIAGRAM_NOT_FOUND", "다이어그램을 찾을 수 없습니다.");
  }
  return fail(404, "NOT_FOUND", "검증용 경로가 없습니다.");
});
server.listen(18080, "127.0.0.1", () =>
  console.log(
    "Frontend contract fixture: http://127.0.0.1:18080 (not a real backend)",
  ),
);

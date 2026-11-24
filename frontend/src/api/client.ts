import { mockApi, type Analysis, type Repository } from "./mock";
import { ApiError } from "./errors";
import * as graph from "./mockGraph";
import type { Catalog, DiagramOptions, DiagramType, GraphDTO } from "./types";
import { readCapabilities, type BackendCapabilities } from "./capabilities";
export const isMock = import.meta.env.VITE_API_MODE !== "real";
const base = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(
  /\/$/,
  "",
);
export type List<T> = { items: T[]; next_cursor: string | null };
export type PageOptions = { cursor?: string | null; limit?: number };
type Summary = Pick<
  Repository,
  "id" | "owner" | "name" | "default_branch" | "latest_run_id"
>;
type RunSummary = Pick<
  Analysis,
  "id" | "commit_sha" | "status" | "progress" | "created_at"
>;
type Start = {
  run_id: string;
  repository_id: string;
  commit_sha: string;
  status: Analysis["status"];
  reused: boolean;
  status_url: string;
};
export type SourceNode = {
  id: number;
  parent_id: number | null;
  kind: string;
  path: string;
  name: string;
  language: string | null;
  parse_status: string;
};
export type SymbolItem = {
  id: number;
  file_id: number;
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  github_url: string;
};
export type SearchItem = {
  kind: "file" | "symbol";
  id: string;
  label: string;
  path: string;
  line: number | null;
};
const object = (v: unknown): v is Record<string, any> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const invalid = () =>
  new ApiError(502, {
    code: "INVALID_RESPONSE",
    message:
      "서버 응답 형식이 API 명세와 다릅니다. 백엔드 연결 상태를 확인해 주세요.",
    details: {},
    request_id: "",
  });
let rateLimit: ApiError | undefined;
async function request<T>(
  path: string,
  init?: RequestInit,
  validate?: (v: any) => boolean,
  url?: string,
): Promise<T> {
  if (rateLimit?.retryAt && rateLimit.retryAt > Date.now()) throw rateLimit;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url || base + path, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
    const body: unknown = await response.json().catch((error) => {
      if (controller.signal.aborted) throw error;
      return null;
    });
    if (!response.ok) {
      const detail = object(body) && object(body.error) ? body.error : {};
      const header = response.headers.get("Retry-After");
      const retryAt = header
        ? /^\d+$/.test(header)
          ? Date.now() + Number(header) * 1000
          : Date.parse(header)
        : undefined;
      const error = new ApiError(
        response.status,
        {
          code: typeof detail.code === "string" ? detail.code : "HTTP_ERROR",
          message:
            typeof detail.message === "string"
              ? detail.message
              : `서버 요청에 실패했습니다. (HTTP ${response.status})`,
          details: object(detail.details) ? detail.details : {},
          request_id:
            typeof detail.request_id === "string"
              ? detail.request_id
              : response.headers.get("X-Request-ID") || "",
        },
        retryAt && Number.isFinite(retryAt) ? retryAt : undefined,
      );
      if (response.status === 429) rateLimit = error;
      throw error;
    }
    if (!object(body) || (validate && !validate(body))) throw invalid();
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, {
      code: controller.signal.aborted ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
      message: controller.signal.aborted
        ? "서버 응답 시간이 초과되었습니다. 요청이 처리됐을 수 있으므로 분석 이력을 확인해 주세요."
        : "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.",
      details: {},
      request_id: "",
    });
  } finally {
    clearTimeout(timer);
  }
}
function query(options: Record<string, string | number | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(options).forEach(([k, v]) => {
    if (v !== null && v !== undefined) params.set(k, String(v));
  });
  return "?" + params.toString();
}
const listShape = (v: any) =>
  Array.isArray(v.items) &&
  (v.next_cursor === null || typeof v.next_cursor === "string");
const repositoryShape = (v: any) =>
  object(v) &&
  typeof v.id === "string" &&
  typeof v.owner === "string" &&
  typeof v.name === "string" &&
  typeof v.default_branch === "string";
const statuses = [
  "queued",
  "fetching",
  "parsing",
  "resolving",
  "completed",
  "partial",
  "failed",
];
const analysisShape = (v: any) =>
  object(v) &&
  typeof v.id === "string" &&
  typeof v.repository_id === "string" &&
  typeof v.commit_sha === "string" &&
  statuses.includes(v.status) &&
  typeof v.progress === "number" &&
  object(v.stats) &&
  [
    "file_count",
    "parsed_files",
    "symbols",
    "resolved_imports",
    "unresolved_imports",
    "tables",
  ].every((k) => v.stats[k] === undefined || typeof v.stats[k] === "number") &&
  Array.isArray(v.warnings) &&
  v.warnings.every((w: unknown) => typeof w === "string");
const graphShape = (v: any) => {
  if (
    typeof v.diagram_id !== "string" ||
    typeof v.run_id !== "string" ||
    !["directory", "dependency", "symbols", "architecture", "erd"].includes(
      v.type,
    ) ||
    !["available", "partial", "unsupported"].includes(v.availability) ||
    !Array.isArray(v.nodes) ||
    v.nodes.length > 300 ||
    !Array.isArray(v.edges) ||
    !Array.isArray(v.warnings) ||
    !v.warnings.every((w: unknown) => typeof w === "string") ||
    typeof v.unresolved_references !== "number" ||
    typeof v.truncated !== "boolean" ||
    typeof v.has_more !== "boolean"
  )
    return false;
  const ids = new Set<string>();
  for (const n of v.nodes) {
    if (
      !object(n) ||
      typeof n.id !== "string" ||
      typeof n.label !== "string" ||
      typeof n.type !== "string" ||
      !object(n.data) ||
      ["path", "language", "github_url"].some(
        (k) => n.data[k] != null && typeof n.data[k] !== "string",
      ) ||
      ids.has(n.id)
    )
      return false;
    ids.add(n.id);
  }
  const edgeIds = new Set<string>();
  return v.edges.every((e: any) => {
    if (
      !object(e) ||
      typeof e.id !== "string" ||
      edgeIds.has(e.id) ||
      !ids.has(e.source) ||
      !ids.has(e.target) ||
      !object(e.data)
    )
      return false;
    const evidence = e.data.evidence;
    const containment = e.type === "contains";
    const schemaReference = v.type === "erd" && e.type === "foreign_key";
    if (
      !(containment && evidence === undefined) &&
      (!Array.isArray(evidence) ||
        !evidence.every(
          (ev: unknown) =>
            object(ev) &&
            (typeof ev.path === "string" ||
              (schemaReference && ev.path === null)) &&
            typeof ev.basis === "string",
        ))
    )
      return false;
    edgeIds.add(e.id);
    return true;
  });
};
function page<T>(items: T[], options: PageOptions): List<T> {
  const offset = Number(options.cursor || 0),
    limit = options.limit || 20;
  return {
    items: items.slice(offset, offset + limit),
    next_cursor: offset + limit < items.length ? String(offset + limit) : null,
  };
}
export const api = {
  getCapabilities: async (): Promise<BackendCapabilities> => {
    if (isMock)
      return {
        commitSha: true,
        repositoryPagination: true,
        historyPagination: true,
      };
    const schemaUrl =
      import.meta.env.VITE_API_SCHEMA_URL ||
      base.replace(/\/api\/v1$/, "") + "/openapi.json";
    const document = await request<Record<string, any>>(
      "",
      undefined,
      (v) => object(v.paths),
      schemaUrl,
    );
    try {
      return readCapabilities(document);
    } catch (error) {
      throw new ApiError(502, {
        code: "INVALID_API_SCHEMA",
        message:
          error instanceof Error
            ? error.message
            : "API 지원 기능을 확인하지 못했습니다.",
        details: {},
        request_id: "",
      });
    }
  },
  listRepositories: async (
    options: PageOptions = {},
  ): Promise<List<Summary>> =>
    isMock
      ? page((await mockApi.listRepositories()).items, options)
      : request(
          "/repositories" + query({ limit: 20, ...options }),
          undefined,
          (v) => listShape(v) && v.items.every(repositoryShape),
        ),
  createRepository: (
    url: string,
  ): Promise<Omit<Repository, "latest_run_id"> & { is_existing: boolean }> =>
    isMock
      ? mockApi.createRepository(url)
      : request(
          "/repositories",
          { method: "POST", body: JSON.stringify({ url }) },
          repositoryShape,
        ),
  getRepository: (id: string): Promise<Repository> =>
    isMock
      ? mockApi.getRepository(id)
      : request(
          `/repositories/${encodeURIComponent(id)}`,
          undefined,
          repositoryShape,
        ),
  listAnalyses: async (
    id: string,
    options: PageOptions = {},
  ): Promise<List<RunSummary>> =>
    isMock
      ? page((await mockApi.listAnalyses(id)).items, options)
      : request(
          `/repositories/${encodeURIComponent(id)}/analyses` +
            query({ limit: 20, ...options }),
          undefined,
          (v) =>
            listShape(v) &&
            v.items.every(
              (r: any) =>
                object(r) &&
                typeof r.id === "string" &&
                typeof r.commit_sha === "string" &&
                typeof r.progress === "number" &&
                statuses.includes(r.status),
            ),
        ),
  startAnalysis: async (id: string, commitSha?: string): Promise<Start> => {
    const sha = commitSha?.trim().toLowerCase();
    if (sha !== undefined && !/^[a-f0-9]{40}$/.test(sha))
      throw new ApiError(422, {
        code: "INVALID_COMMIT_SHA",
        message: "커밋 SHA 40자리를 확인해 주세요.",
        details: {},
        request_id: "",
      });
    const result = isMock
      ? await mockApi.startAnalysis(
          id,
          sha ?? "0123456789abcdef0123456789abcdef01234567",
        )
      : await request<Start>(
          `/repositories/${encodeURIComponent(id)}/analyses`,
          {
            method: "POST",
            ...(sha !== undefined
              ? { body: JSON.stringify({ commit_sha: sha }) }
              : {}),
          },
          (v) =>
            typeof v.run_id === "string" &&
            typeof v.commit_sha === "string" &&
            statuses.includes(v.status),
        );
    if (sha !== undefined && result.commit_sha.toLowerCase() !== sha)
      throw new ApiError(409, {
        code: "COMMIT_SHA_MISMATCH",
        message:
          "서버가 입력한 커밋과 다른 SHA를 반환했습니다. 분석 이력을 확인하고 백엔드의 지정 커밋 지원 여부를 확인해 주세요.",
        details: {
          requested: sha,
          actual: result.commit_sha,
          run_id: result.run_id,
        },
        request_id: "",
      });
    return result;
  },
  getAnalysis: async (id: string): Promise<Analysis> => {
    const result = isMock
      ? await mockApi.getAnalysis(id)
      : await request<
          Omit<Analysis, "stats"> & { stats: Partial<Analysis["stats"]> }
        >(`/analyses/${encodeURIComponent(id)}`, undefined, analysisShape);
    return {
      ...result,
      stats: {
        file_count: 0,
        parsed_files: 0,
        symbols: 0,
        resolved_imports: 0,
        unresolved_imports: 0,
        tables: 0,
        ...result.stats,
      },
    };
  },
  search: async (
    id: string,
    q: string,
    options: PageOptions = {},
  ): Promise<List<SearchItem>> =>
    isMock
      ? page((await graph.search(id, q)).items, options)
      : request(
          `/analyses/${encodeURIComponent(id)}/search` +
            query({ q, kind: "all", limit: 20, ...options }),
          undefined,
          (v) =>
            listShape(v) &&
            v.items.every(
              (x: any) =>
                object(x) &&
                ["file", "symbol"].includes(x.kind) &&
                typeof x.id === "string" &&
                typeof x.path === "string" &&
                typeof x.label === "string",
            ),
        ),
  listNodes: async (
    id: string,
    options: PageOptions & { root_path?: string; depth?: number } = {},
  ): Promise<List<SourceNode>> => {
    if (!isMock)
      return request(
        `/analyses/${encodeURIComponent(id)}/nodes` +
          query({ root_path: ".", depth: 8, limit: 100, ...options }),
        undefined,
        (v) =>
          listShape(v) &&
          v.items.every(
            (n: unknown) =>
              object(n) &&
              typeof n.id === "number" &&
              typeof n.path === "string" &&
              typeof n.kind === "string",
          ),
      );
    const data = await graph.createGraph(id, "directory", {
      root_path: options.root_path || ".",
      depth: 8,
      max_nodes: 300,
    });
    return page(
      data.nodes.map((n) => ({
        id: Number(n.id.slice(n.id.indexOf(":") + 1)) || 0,
        parent_id: null,
        kind: n.type,
        path: n.data.path || ".",
        name: n.label,
        language: n.data.language || null,
        parse_status: "parsed",
      })),
      options,
    );
  },
  listSymbols: (id: string, fileId: number): Promise<List<SymbolItem>> =>
    isMock
      ? graph.mockSymbols(id, fileId)
      : request(
          `/analyses/${encodeURIComponent(id)}/symbols` +
            query({ file_id: fileId, limit: 1 }),
          undefined,
          listShape,
        ),
  getCatalog: (id: string): Promise<Catalog> =>
    isMock
      ? graph.catalog(id)
      : request(
          `/analyses/${encodeURIComponent(id)}/diagram-types`,
          undefined,
          (v) =>
            Array.isArray(v.items) &&
            v.items.every(
              (i: any) =>
                object(i) &&
                [
                  "directory",
                  "dependency",
                  "symbols",
                  "architecture",
                  "erd",
                ].includes(i.type) &&
                ["available", "partial", "unsupported"].includes(
                  i.availability,
                ) &&
                (i.reason === null || typeof i.reason === "string"),
            ),
        ),
  createDiagram: (
    id: string,
    type: DiagramType,
    options: DiagramOptions,
  ): Promise<GraphDTO> =>
    isMock
      ? graph.createGraph(id, type, options)
      : request(
          `/analyses/${encodeURIComponent(id)}/diagrams`,
          { method: "POST", body: JSON.stringify({ type, options }) },
          graphShape,
        ),
  getDiagram: (id: string): Promise<GraphDTO> =>
    isMock
      ? graph.getGraph(id)
      : request(`/diagrams/${encodeURIComponent(id)}`, undefined, graphShape),
};

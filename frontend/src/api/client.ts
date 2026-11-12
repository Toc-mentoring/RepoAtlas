import { mockApi, ApiError, type Analysis, type Repository } from "./mock";
import * as graph from "./mockGraph";
import type { Catalog, DiagramOptions, DiagramType, GraphDTO } from "./types";
export const isMock = import.meta.env.VITE_API_MODE !== "real";
type List<T> = { items: T[]; next_cursor: string | null };
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
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      body = {
        error: {
          code: "HTTP_ERROR",
          message: "서버 요청에 실패했습니다.",
          details: {},
          request_id: "",
        },
      };
    }
    throw new ApiError(response.status, body.error);
  }
  return response.json() as Promise<T>;
}
export const api = {
  listRepositories: (): Promise<List<Summary>> =>
    isMock ? mockApi.listRepositories() : request("/repositories"),
  createRepository: (
    url: string,
  ): Promise<Omit<Repository, "latest_run_id"> & { is_existing: boolean }> =>
    isMock
      ? mockApi.createRepository(url)
      : request("/repositories", {
          method: "POST",
          body: JSON.stringify({ url }),
        }),
  getRepository: (id: string): Promise<Repository> =>
    isMock
      ? mockApi.getRepository(id)
      : request(`/repositories/${encodeURIComponent(id)}`),
  listAnalyses: (id: string): Promise<List<RunSummary>> =>
    isMock
      ? mockApi.listAnalyses(id)
      : request(`/repositories/${encodeURIComponent(id)}/analyses`),
  startAnalysis: (id: string, commitSha: string): Promise<Start> =>
    isMock
      ? mockApi.startAnalysis(id, commitSha)
      : request(`/repositories/${encodeURIComponent(id)}/analyses`, {
          method: "POST",
          body: JSON.stringify({ commit_sha: commitSha }),
        }),
  getAnalysis: (id: string): Promise<Analysis> =>
    isMock
      ? mockApi.getAnalysis(id)
      : request(`/analyses/${encodeURIComponent(id)}`),
  search: (
    id: string,
    q: string,
  ): Promise<
    List<{
      kind: "file" | "symbol";
      id: string;
      label: string;
      path: string;
      line: number | null;
    }>
  > =>
    isMock
      ? graph.search(id, q)
      : request(
          `/analyses/${encodeURIComponent(id)}/search?${new URLSearchParams({ q, kind: "all", limit: "20" })}`,
        ),
  getCatalog: (id: string): Promise<Catalog> =>
    isMock
      ? graph.catalog(id)
      : request(`/analyses/${encodeURIComponent(id)}/diagram-types`),
  createDiagram: (
    id: string,
    type: DiagramType,
    options: DiagramOptions,
  ): Promise<GraphDTO> =>
    isMock
      ? graph.createGraph(id, type, options)
      : request(`/analyses/${encodeURIComponent(id)}/diagrams`, {
          method: "POST",
          body: JSON.stringify({ type, options }),
        }),
  getDiagram: (id: string): Promise<GraphDTO> =>
    isMock
      ? graph.getGraph(id)
      : request(`/diagrams/${encodeURIComponent(id)}`),
};

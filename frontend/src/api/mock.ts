export type Status =
  | "queued"
  | "fetching"
  | "parsing"
  | "resolving"
  | "completed"
  | "partial"
  | "failed";
export type Repository = {
  id: string;
  provider: "github";
  owner: string;
  name: string;
  canonical_url: string;
  default_branch: string;
  latest_run_id: string | null;
  created_at: string;
};
export type Analysis = {
  id: string;
  repository_id: string;
  commit_sha: string;
  status: Status;
  progress: number;
  stats: {
    file_count: number;
    parsed_files: number;
    symbols: number;
    resolved_imports: number;
    unresolved_imports: number;
    tables: number;
  };
  warnings: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
};
type Database = { repositories: Repository[]; runs: Analysis[] };
export class ApiError extends Error {
  constructor(
    public status: number,
    public error: {
      code: string;
      message: string;
      details: Record<string, unknown>;
      request_id: string;
    },
  ) {
    super(error.message);
  }
}
const key = "repoatlas.mock.v2";
const now = () => new Date().toISOString();
const uuid = () => crypto.randomUUID();
const sha = "0123456789abcdef0123456789abcdef01234567";
const stats = {
  file_count: 150,
  parsed_files: 70,
  symbols: 240,
  resolved_imports: 120,
  unresolved_imports: 12,
  tables: 3,
};
function seed(): Database {
  const configs = [
    ["facebook", "react", "completed"],
    ["vercel", "next.js", "partial"],
    ["example", "api-server", "failed"],
  ] as const;
  const repositories: Repository[] = [];
  const runs: Analysis[] = [];
  for (const [owner, name, status] of configs) {
    const id = uuid(),
      rid = uuid();
    repositories.push({
      id,
      provider: "github",
      owner,
      name,
      canonical_url: `https://github.com/${owner}/${name}`,
      default_branch: "main",
      latest_run_id: rid,
      created_at: now(),
    });
    runs.push({
      id: rid,
      repository_id: id,
      commit_sha: sha,
      status,
      progress: status === "failed" ? 60 : 100,
      stats,
      warnings:
        status === "partial" ? ["일부 파일을 분석하지 못했습니다."] : [],
      error_code: status === "failed" ? "ANALYSIS_FAILED" : null,
      error_message:
        status === "failed" ? "저장소 분석 중 오류가 발생했습니다." : null,
      created_at: now(),
      finished_at: now(),
    });
  }
  return { repositories, runs };
}
function read(): Database {
  try {
    const value = localStorage.getItem(key);
    if (value) return JSON.parse(value) as Database;
  } catch {
    localStorage.removeItem(key);
  }
  const db = seed();
  write(db);
  return db;
}
function write(db: Database) {
  localStorage.setItem(key, JSON.stringify(db));
}
function fail(status: number, code: string, message: string): never {
  throw new ApiError(status, {
    code,
    message,
    details: {},
    request_id: `mock-${uuid().slice(0, 8)}`,
  });
}
const delay = () => new Promise<void>((resolve) => setTimeout(resolve, 350));
function advance(run: Analysis): Analysis {
  if (["completed", "partial", "failed"].includes(run.status)) return run;
  const seconds = (Date.now() - Date.parse(run.created_at)) / 1000;
  const [status, progress]: [Status, number] =
    seconds < 2
      ? ["queued", 0]
      : seconds < 4
        ? ["fetching", 20]
        : seconds < 6
          ? ["parsing", 55]
          : seconds < 8
            ? ["resolving", 85]
            : ["completed", 100];
  return {
    ...run,
    status,
    progress,
    finished_at: status === "completed" ? now() : null,
  };
}
export const mockApi = {
  async listRepositories() {
    await delay();
    const db = read();
    return {
      items: db.repositories.map(
        ({ id, owner, name, default_branch, latest_run_id }) => ({
          id,
          owner,
          name,
          default_branch,
          latest_run_id,
        }),
      ),
      next_cursor: null,
    };
  },
  async createRepository(url: string) {
    await delay();
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      return fail(
        422,
        "INVALID_REPOSITORY_URL",
        "올바른 GitHub 저장소 URL을 입력해 주세요.",
      );
    }
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (
      parsed.protocol !== "https:" ||
      parsed.hostname !== "github.com" ||
      parts.length !== 2 ||
      parsed.search ||
      parsed.hash ||
      parsed.username ||
      parsed.password ||
      !parts.every((p) => /^[\w.-]+$/.test(p))
    )
      return fail(
        422,
        "INVALID_REPOSITORY_URL",
        "https://github.com/소유자/저장소 형식으로 입력해 주세요.",
      );
    const db = read();
    let repo = db.repositories.find(
      (r) =>
        r.owner.toLowerCase() === parts[0].toLowerCase() &&
        r.name.toLowerCase() === parts[1].toLowerCase(),
    );
    const is_existing = !!repo;
    if (!repo) {
      repo = {
        id: uuid(),
        provider: "github",
        owner: parts[0],
        name: parts[1],
        canonical_url: `https://github.com/${parts[0]}/${parts[1]}`,
        default_branch: "main",
        latest_run_id: null,
        created_at: now(),
      };
      db.repositories.unshift(repo);
      write(db);
    }
    const { latest_run_id: _, ...response } = repo;
    return { ...response, is_existing };
  },
  async getRepository(id: string) {
    await delay();
    return (
      read().repositories.find((r) => r.id === id) ??
      fail(404, "REPOSITORY_NOT_FOUND", "저장소를 찾을 수 없습니다.")
    );
  },
  async listAnalyses(id: string) {
    await delay();
    const db = read();
    if (!db.repositories.some((r) => r.id === id))
      return fail(404, "REPOSITORY_NOT_FOUND", "저장소를 찾을 수 없습니다.");
    return {
      items: db.runs
        .filter((r) => r.repository_id === id)
        .map(advance)
        .map(({ id, commit_sha, status, progress, created_at }) => ({
          id,
          commit_sha,
          status,
          progress,
          created_at,
        })),
      next_cursor: null,
    };
  },
  async startAnalysis(id: string, commitSha: string) {
    await delay();
    commitSha = commitSha.trim().toLowerCase();
    if (!/^[0-9a-f]{40}$/.test(commitSha))
      return fail(
        422,
        "INVALID_COMMIT_SHA",
        "커밋 해시는 40자리 16진수여야 합니다.",
      );
    const db = read();
    const repo = db.repositories.find((r) => r.id === id);
    if (!repo)
      return fail(404, "REPOSITORY_NOT_FOUND", "저장소를 찾을 수 없습니다.");
    let run = db.runs
      .filter((r) => r.repository_id === id)
      .map(advance)
      .find(
        (r) =>
          r.commit_sha === commitSha &&
          (r.status === "completed" ||
            ["queued", "fetching", "parsing", "resolving"].includes(r.status)),
      );
    const reused = !!run;
    if (!run) {
      run = {
        id: uuid(),
        repository_id: id,
        commit_sha: commitSha,
        status: "queued",
        progress: 0,
        stats: {
          file_count: 0,
          parsed_files: 0,
          symbols: 0,
          resolved_imports: 0,
          unresolved_imports: 0,
          tables: 0,
        },
        warnings: [],
        error_code: null,
        error_message: null,
        created_at: now(),
        finished_at: null,
      };
      db.runs.unshift(run);
    }
    repo.latest_run_id = run.id;
    write(db);
    return {
      run_id: run.id,
      repository_id: id,
      commit_sha: run.commit_sha,
      status: run.status,
      reused,
      status_url: `/api/v1/analyses/${run.id}`,
    };
  },
  async getAnalysis(id: string) {
    await delay();
    const db = read();
    const index = db.runs.findIndex((r) => r.id === id);
    if (index < 0)
      return fail(404, "ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없습니다.");
    const run = advance(db.runs[index]);
    if (run.status === "completed") run.stats = stats;
    db.runs[index] = run;
    write(db);
    return run;
  },
};

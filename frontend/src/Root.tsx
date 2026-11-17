import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  Box,
  GitBranch,
  Plus,
  ArrowRight,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Sun,
  Moon,
} from "lucide-react";
import { type Status } from "./api/mock";
import { Feedback, MoreButton } from "./components/Feedback";
import { nextPage, pageItems } from "./api/pages";
import { api, isMock } from "./api/client";
import {
  AnalysisTarget,
  useBackendCapabilities,
} from "./components/AnalysisTarget";
import {
  useMutation,
  useQuery,
  useQueryClient,
  useInfiniteQuery,
} from "@tanstack/react-query";
import { DiagramChooser, GraphPage } from "./features/diagrams/GraphPage";

import "./style.css";
const labels: Record<Status, string> = {
  queued: "대기 중",
  fetching: "수집 중",
  parsing: "분석 중",
  resolving: "관계 확인 중",
  completed: "분석 완료",
  partial: "부분 완료",
  failed: "분석 실패",
};
const terminal = (status: Status) =>
  ["completed", "partial", "failed"].includes(status);
function Shell({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("repoatlas.theme");
    return saved === "light" || saved === "dark"
      ? saved
      : window.matchMedia?.("(prefers-color-scheme: light)").matches
        ? "light"
        : "dark";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("repoatlas.theme", theme);
  }, [theme]);
  return (
    <div className="app">
      <header className="top">
        <Link className="brand" to="/">
          <span className="brandmark">
            <Box size={19} />
          </span>
          <b>RepoAtlas</b>
        </Link>
        <span className="divider" />
        <Link className="crumb" to="/">
          Repositories
        </Link>
        <div className="topright">
          <span className="environment-label">
            {isMock ? "예시 데이터" : "API 연결"}
          </span>
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={
              theme === "dark" ? "라이트 모드로 변경" : "다크 모드로 변경"
            }
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            <span>{theme === "dark" ? "라이트" : "다크"} 모드</span>
          </button>
        </div>
      </header>
      {children}
      <footer>
        <span>RepoAtlas / Repository intelligence</span>
        <span>
          <CheckCircle2 size={13} /> {isMock ? "Mock 환경" : "API 환경"}
        </span>
      </footer>
    </div>
  );
}
function StatusBadge({ status }: { status: Status }) {
  return <span className={"status " + status}>{labels[status]}</span>;
}
function Home() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [commitSha, setCommitSha] = useState("");
  const capabilities = useBackendCapabilities();
  const list = useInfiniteQuery({
    queryKey: ["repositories"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api.listRepositories({
        cursor: pageParam,
        ...(capabilities.data?.repositoryPagination === false
          ? { limit: 100 }
          : {}),
      }),
    enabled: !capabilities.isPending,
    getNextPageParam: nextPage,
  });
  const repositories = pageItems(list.data?.pages);
  const [registeredId, setRegisteredId] = useState<string | null>(null);
  const registration = useMutation({
    mutationFn: async () => {
      if (!capabilities.data || capabilities.isError)
        throw new Error("서버 지원 기능을 확인한 뒤 다시 시도해 주세요.");
      const repo = await api.createRepository(url.trim());
      setRegisteredId(repo.id);
      await queryClient.invalidateQueries({ queryKey: ["repositories"] });
      return api.startAnalysis(
        repo.id,
        capabilities.data.commitSha
          ? commitSha.trim().toLowerCase()
          : undefined,
      );
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["repositories"] });
      navigate(`/runs/${run.run_id}`);
    },
  });
  function register(e: React.FormEvent) {
    e.preventDefault();
    if (!registration.isPending) registration.mutate();
  }
  return (
    <main className="home">
      <div className="heading">
        <div>
          <h1>저장소</h1>
          <p>코드의 구조를 한눈에 살펴보세요.</p>
        </div>
        <span className="count">
          {list.isLoading
            ? "불러오는 중"
            : list.isError && !repositories.length
              ? "조회 실패"
              : `${repositories.length}개 저장소 표시 중`}
        </span>
      </div>
      <section className="add-card">
        <div className="add-icon">
          <Plus size={21} />
        </div>
        <div className="add-content">
          <h2>새 저장소 분석하기</h2>
          <p>
            {capabilities.data?.commitSha
              ? "공개 GitHub 저장소 주소와 분석할 커밋 해시를 입력해 주세요."
              : "공개 GitHub 저장소의 기본 브랜치를 분석합니다."}
          </p>
          <form onSubmit={register}>
            <label className="field">
              <span>GitHub 저장소 URL</span>
              <div className="input-wrap">
                <GitBranch size={17} />
                <input
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    registration.reset();
                  }}
                  placeholder="https://github.com/owner/repository"
                  aria-label="GitHub 저장소 URL"
                  required
                />
              </div>
            </label>
            <AnalysisTarget
              capabilities={capabilities}
              sha={commitSha}
              onChange={(value) => {
                setCommitSha(value);
                registration.reset();
              }}
            />
            <button
              className="primary"
              disabled={
                registration.isPending ||
                !capabilities.data ||
                capabilities.isError
              }
            >
              {registration.isPending ? "요청 중…" : "분석 요청"}{" "}
              <ArrowRight size={16} />
            </button>
          </form>
          {registration.isError && (
            <>
              <Feedback error={registration.error} />
              {registeredId && (
                <Link to={`/repositories/${registeredId}`}>
                  등록된 저장소와 분석 이력 확인
                </Link>
              )}
            </>
          )}
          <small>
            {isMock
              ? "예시 환경입니다. 실제 GitHub 접근이나 분석은 수행하지 않습니다."
              : "공개 GitHub 저장소만 지원합니다."}
          </small>
        </div>
      </section>
      <div className="section-head">
        <h2>내 저장소</h2>
        <p>등록한 저장소와 분석 이력을 확인하세요.</p>
      </div>
      {list.isError && (
        <Feedback
          error={list.error}
          retry={() =>
            list.isFetchNextPageError ? list.fetchNextPage() : list.refetch()
          }
        />
      )}
      <div className="repo-list">
        {list.isLoading ? (
          <div className="empty" role="status">
            저장소를 불러오는 중입니다…
          </div>
        ) : !list.isError && !repositories.length ? (
          <div className="empty">등록된 저장소가 없습니다.</div>
        ) : (
          <>
            <div className="table-head">
              <span>저장소</span>
              <span>기본 브랜치</span>
              <span>분석 이력</span>
              <span />
            </div>
            {repositories.map((r) => (
              <div className="repo-row" key={r.id}>
                <div className="repo-name">
                  <span className="repo-icon">
                    <GitBranch size={17} />
                  </span>
                  <div>
                    <b>{r.name}</b>
                    <small>
                      {r.owner} / {r.name}
                    </small>
                  </div>
                </div>
                <span className="muted">{r.default_branch}</span>
                <span className="muted">
                  {r.latest_run_id ? "분석 이력 있음" : "분석 전"}
                </span>
                <Link className="row-action" to={`/repositories/${r.id}`}>
                  열기 <ChevronRight size={16} />
                </Link>
              </div>
            ))}
          </>
        )}
      </div>
      {capabilities.data?.repositoryPagination === false && (
        <p className="muted">
          현재 서버는 저장소 페이지 넘기기를 지원하지 않아 최근 최대 100개를
          표시합니다.
        </p>
      )}
      <MoreButton
        more={!!list.hasNextPage}
        pending={list.isFetching}
        load={() => list.fetchNextPage()}
      />
    </main>
  );
}
function RepositoryPage() {
  const { repoId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [commitSha, setCommitSha] = useState("");
  const capabilities = useBackendCapabilities();
  const repo = useQuery({
    queryKey: ["repository", repoId],
    queryFn: () => api.getRepository(repoId),
  });
  const runs = useInfiniteQuery({
    queryKey: ["analyses", repoId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api.listAnalyses(repoId, {
        cursor: pageParam,
        ...(capabilities.data?.historyPagination === false
          ? { limit: 100 }
          : {}),
      }),
    enabled: !capabilities.isPending,
    getNextPageParam: nextPage,
  });
  const analyses = pageItems(runs.data?.pages);
  const start = useMutation({
    mutationFn: () => {
      if (!capabilities.data || capabilities.isError)
        throw new Error("서버 지원 기능을 확인한 뒤 다시 시도해 주세요.");
      return api.startAnalysis(
        repoId,
        capabilities.data.commitSha
          ? commitSha.trim().toLowerCase()
          : undefined,
      );
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["analyses", repoId] });
      queryClient.invalidateQueries({ queryKey: ["repositories"] });
      navigate(`/runs/${result.run_id}`);
    },
  });
  if (repo.isLoading || runs.isLoading)
    return (
      <main className="home" role="status">
        저장소를 불러오는 중입니다…
      </main>
    );
  if (repo.isError || !repo.data)
    return (
      <main className="home">
        <Feedback error={repo.error} retry={() => repo.refetch()} />
        <Link className="back" to="/">
          ← 저장소 목록
        </Link>
      </main>
    );
  return (
    <main className="home">
      <Link className="back" to="/">
        ← 모든 저장소
      </Link>
      <div className="heading">
        <div>
          <h1>
            {repo.data.owner} / {repo.data.name}
          </h1>
          <p>
            <GitBranch size={14} /> {repo.data.default_branch} ·{" "}
            {repo.data.canonical_url}
          </p>
        </div>
        <button
          className="primary action"
          form="analysis-form"
          disabled={
            start.isPending || !capabilities.data || capabilities.isError
          }
        >
          {start.isPending ? "요청 중…" : "분석 요청"} <ArrowRight size={16} />
        </button>
      </div>
      <form
        id="analysis-form"
        className="analysis-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!start.isPending) start.mutate();
        }}
      >
        <AnalysisTarget
          capabilities={capabilities}
          sha={commitSha}
          onChange={setCommitSha}
        />
      </form>
      {start.isError && <Feedback error={start.error} />}{" "}
      {runs.isError && (
        <Feedback
          error={runs.error}
          retry={() =>
            runs.isFetchNextPageError ? runs.fetchNextPage() : runs.refetch()
          }
        />
      )}{" "}
      {isMock && (
        <div className="notice">
          <Clock3 size={16} /> 예시 환경에서는 분석 진행을 시뮬레이션합니다.
          실제 저장소는 수집하지 않습니다.
        </div>
      )}
      <div className="section-head">
        <h2>분석 이력</h2>
        <p>분석을 선택하면 진행 상태와 결과를 확인할 수 있습니다.</p>
      </div>
      <div className="repo-list">
        {!runs.isError && !analyses.length ? (
          <div className="empty">
            아직 분석 이력이 없습니다. 분석 요청을 눌러 시작하세요.
          </div>
        ) : (
          analyses.map((r) => (
            <div className="repo-row" key={r.id}>
              <div className="repo-name">
                <span className="repo-icon">
                  <GitBranch size={17} />
                </span>
                <div>
                  <b>{r.commit_sha.slice(0, 7)}</b>
                  <small>
                    {new Date(r.created_at).toLocaleString("ko-KR")}
                  </small>
                </div>
              </div>
              <span className="muted">{r.progress}%</span>
              <StatusBadge status={r.status} />
              <Link className="row-action" to={`/runs/${r.id}`}>
                확인 <ChevronRight size={16} />
              </Link>
            </div>
          ))
        )}
      </div>
      {capabilities.data?.historyPagination === false && (
        <p className="muted">
          현재 서버는 분석 이력 페이지 넘기기를 지원하지 않아 최근 최대 100개를
          표시합니다.
        </p>
      )}
      <MoreButton
        more={!!runs.hasNextPage}
        pending={runs.isFetching}
        load={() => runs.fetchNextPage()}
      />
    </main>
  );
}
function RunPage() {
  const { runId = "" } = useParams();
  const run = useQuery({
    queryKey: ["analysis", runId],
    queryFn: () => api.getAnalysis(runId),
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.data &&
      !terminal(query.state.data.status)
        ? 2000
        : false,
    retry: false,
  });
  const repo = useQuery({
    queryKey: ["repository", run.data?.repository_id],
    queryFn: () => api.getRepository(run.data!.repository_id),
    enabled: !!run.data?.repository_id,
    retry: false,
  });
  if (run.isLoading)
    return (
      <main className="home" role="status">
        분석 상태를 불러오는 중입니다…
      </main>
    );
  if (!run.data)
    return (
      <main className="home">
        <Feedback error={run.error} retry={() => run.refetch()} />
        <Link className="back" to="/">
          ← 저장소 목록
        </Link>
      </main>
    );
  const value = run.data;
  return (
    <main className="home run-home">
      <Link className="back" to={`/repositories/${value.repository_id}`}>
        ← 저장소 상세
      </Link>
      <div className="heading">
        <div>
          <h1>
            {repo.data ? `${repo.data.owner} / ${repo.data.name}` : "분석 상태"}
          </h1>
          <p>
            고정 커밋 {value.commit_sha.slice(0, 7)} / 분석{" "}
            {value.id.slice(0, 8)} {isMock ? "/ 예시 분석" : ""}
          </p>
        </div>
        <StatusBadge status={value.status} />
      </div>
      {repo.isError && (
        <Feedback error={repo.error} retry={() => repo.refetch()} />
      )}
      {run.isError && (
        <Feedback error={run.error} retry={() => run.refetch()} />
      )}
      <section className="run-card">
        <div className="progress-head">
          <div>
            <h2>{labels[value.status]}</h2>
            <p>
              {terminal(value.status)
                ? "분석이 종료되었습니다."
                : "2초마다 진행 상황을 확인합니다."}
            </p>
          </div>
          <strong>{value.progress}%</strong>
        </div>
        <progress value={value.progress} max={100} aria-label="분석 진행률" />
        <div className="steps">
          대기 <span>→</span> 수집 <span>→</span> 분석 <span>→</span> 관계 확인{" "}
          <span>→</span> 완료
        </div>
      </section>
      {(value.status === "partial" || value.warnings.length > 0) && (
        <div className="notice">
          <AlertTriangle size={16} />
          <div>
            <b>
              {value.status === "partial"
                ? "일부 분석이 완료되지 않았습니다."
                : "분석 경고"}
            </b>{" "}
            {value.warnings.join(" ")}
          </div>
        </div>
      )}
      {value.status === "failed" && (
        <div className="notice fail">
          <AlertTriangle size={16} />
          <div>
            <b>분석에 실패했습니다.</b> {value.error_message}{" "}
            {value.error_code && `(${value.error_code})`}{" "}
            <Link to={`/repositories/${value.repository_id}`}>
              돌아가서 다시 요청
            </Link>
          </div>
        </div>
      )}
      {(value.status === "completed" || value.status === "partial") && (
        <>
          <div className="section-head">
            <h2>분석 결과</h2>
            <p>
              파일 {value.stats.file_count}개 / 심볼 {value.stats.symbols}개 /
              해결된 import {value.stats.resolved_imports}개
            </p>
          </div>
          <Link
            className="primary action diagram-link"
            to={`/runs/${value.id}/diagrams`}
          >
            다이어그램 보기 <ArrowRight size={16} />
          </Link>
        </>
      )}
    </main>
  );
}
function DiagramPage() {
  const { runId = "" } = useParams();
  return (
    <main className="home run-home">
      <Link className="back" to={`/runs/${runId}`}>
        ← 분석 결과
      </Link>
      <DiagramChooser runId={runId} />
    </main>
  );
}
function NotFound() {
  return (
    <main className="home">
      <h1>페이지를 찾을 수 없습니다</h1>
      <Link className="back" to="/">
        저장소 목록으로 돌아가기
      </Link>
    </main>
  );
}
export default function Root() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="*"
          element={
            <Shell>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/repositories" element={<Home />} />
                <Route
                  path="/repositories/:repoId"
                  element={<RepositoryPage />}
                />
                <Route path="/runs/:runId" element={<RunPage />} />
                <Route path="/runs/:runId/diagrams" element={<DiagramPage />} />
                <Route path="/diagrams/:id" element={<GraphPage />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Shell>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

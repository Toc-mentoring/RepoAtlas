import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { ExternalLink, AlertTriangle } from "lucide-react";
import { NodeExplorer } from "./NodeExplorer";
import { api, isMock } from "../../api/client";
import { ApiError } from "../../api/mock";
import type { DiagramOptions, DiagramType, GraphDTO } from "../../api/types";
import "@xyflow/react/dist/style.css";
const names: Record<DiagramType, string> = {
  directory: "폴더 구조",
  dependency: "의존성",
  symbols: "심볼",
  architecture: "아키텍처",
  erd: "ERD",
};
function text(e: unknown) {
  return e instanceof ApiError
    ? e.message
    : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";
}
export function DiagramChooser({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const catalog = useQuery({
    queryKey: ["catalog", runId],
    queryFn: () => api.getCatalog(runId),
  });
  const open = useMutation({
    mutationFn: async (type: DiagramType) => {
      const options: DiagramOptions = { max_nodes: 150 };
      if (type === "symbols") {
        const directory = await api.createDiagram(runId, "directory", {
          root_path: ".",
          depth: 8,
          max_nodes: 300,
        });
        const file = directory.nodes.find((node) =>
          node.id.startsWith("file:"),
        );
        if (!file) throw new Error("심볼을 표시할 파일을 찾지 못했습니다.");
        options.file_id = Number(file.id.slice(5));
      } else if (type === "directory" || type === "dependency") {
        options.root_path = ".";
        options.depth = 2;
      }
      return api.createDiagram(runId, type, options);
    },
    onSuccess: (data) => navigate("/diagrams/" + data.diagram_id),
  });
  return (
    <section className="diagram-chooser">
      <div className="section-head">
        <h1>다이어그램</h1>
        <p>
          확인할 다이어그램을 선택하세요. 심볼은 첫 번째 파일을 기준으로
          표시됩니다.
        </p>
      </div>
      {catalog.isLoading && <p role="status">지원 유형을 불러오는 중입니다…</p>}
      {catalog.isError && (
        <p role="alert">
          {text(catalog.error)}{" "}
          <button onClick={() => catalog.refetch()}>다시 시도</button>
        </p>
      )}
      {catalog.data && (
        <div className="diagram-catalog">
          {catalog.data.items.map((item) => (
            <button
              key={item.type}
              disabled={item.availability === "unsupported" || open.isPending}
              onClick={() => open.mutate(item.type)}
              title={item.reason ?? undefined}
            >
              {names[item.type]}{" "}
              <small>
                {item.availability === "unsupported"
                  ? "미지원 · " + item.reason
                  : item.availability === "partial"
                    ? "부분 지원 · " + item.reason
                    : "바로 보기"}
              </small>
            </button>
          ))}
        </div>
      )}
      {open.isPending && <p role="status">다이어그램을 불러오는 중입니다…</p>}
      {open.isError && (
        <p className="error" role="alert">
          {open.error instanceof Error ? open.error.message : text(open.error)}
        </p>
      )}
    </section>
  );
}
function layout(
  graph: GraphDTO,
  search: string,
  selected: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 35, ranksep: 95 });
  graph.nodes.forEach((n) => g.setNode(n.id, { width: 180, height: 60 }));
  graph.edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const matches = search.trim().toLowerCase();
  const connected = new Set(
    graph.edges
      .filter((e) => e.source === selected || e.target === selected)
      .map((e) => e.id),
  );
  return {
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      position: { x: g.node(n.id).x - 90, y: g.node(n.id).y - 30 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        label: (
          <>
            <span className="node-icon">
              {n.type === "directory" ? "▸" : "◇"}
            </span>
            <span>
              <strong>{n.label}</strong>
              <small>{n.data.path ?? n.type}</small>
            </span>
          </>
        ),
      },
      className: `file-node ${matches && !`${n.label} ${n.data.path ?? ""}`.toLowerCase().includes(matches) ? "dim" : ""}`,
    })),
    edges: graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      markerEnd: { type: MarkerType.ArrowClosed, color: "var(--graph-edge)" },
      style: {
        stroke:
          selected && !connected.has(e.id)
            ? "var(--graph-edge-muted)"
            : "var(--graph-edge)",
        strokeWidth: connected.has(e.id) ? 3 : 1.5,
        strokeDasharray: e.data.certainty === "inferred" ? "6 4" : undefined,
      },
    })),
  };
}
type DiagramParent = { id: string; previous?: DiagramParent };
export function GraphPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const parent = (location.state as { parent?: DiagramParent } | null)?.parent;
  const graph = useQuery({
    queryKey: ["diagram", id],
    queryFn: () => api.getDiagram(id),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [panels, setPanels] = useState<"graph" | "tree" | "details">("graph");
  const create = useMutation({
    mutationFn: ({
      type,
      options,
    }: {
      type: DiagramType;
      options: DiagramOptions;
    }) => api.createDiagram(graph.data!.run_id, type, options),
    onSuccess: (data) => {
      setSelected(null);
      navigate(`/diagrams/${data.diagram_id}`, {
        state: { parent: { id, previous: parent } },
      });
    },
  });
  const rendered = useMemo(
    () =>
      graph.data
        ? layout(graph.data, search, selected)
        : { nodes: [], edges: [] },
    [graph.data, search, selected],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  useEffect(() => {
    setNodes(rendered.nodes);
    setEdges(rendered.edges);
  }, [rendered, setNodes, setEdges]);
  if (graph.isLoading)
    return (
      <main className="home" role="status">
        다이어그램을 불러오는 중입니다…
      </main>
    );
  if (graph.isError || !graph.data)
    return (
      <main className="home">
        <div className="notice fail" role="alert">
          {text(graph.error)}{" "}
          <button onClick={() => graph.refetch()}>다시 시도</button>
        </div>
        <Link to="/">저장소 목록</Link>
      </main>
    );
  const data = graph.data;
  const active = data.nodes.find((n) => n.id === selected);
  const fileId = active?.id.startsWith("file:")
    ? Number(active.id.slice(5))
    : null;
  return (
    <>
      <div className="workspace-head">
        <div>
          {parent ? (
            <Link
              className="back"
              to={`/diagrams/${parent.id}`}
              state={{ parent: parent.previous }}
            >
              ← 이전 다이어그램
            </Link>
          ) : (
            <Link className="back" to={`/runs/${data.run_id}/diagrams`}>
              ← 다이어그램 선택
            </Link>
          )}
          <h1>{names[data.type]}</h1>
          <p>
            노드 {data.nodes.length}개 / 관계 {data.edges.length}개{" "}
            {isMock ? "/ 예시 데이터" : ""}
          </p>
        </div>
        <div className="mobile-panels">
          <button onClick={() => setPanels("tree")}>탐색기</button>
          <button onClick={() => setPanels("graph")}>그래프</button>
          <button onClick={() => setPanels("details")}>상세</button>
        </div>
      </div>
      {(data.warnings.length > 0 || data.truncated || data.has_more) && (
        <div className="notice">
          <AlertTriangle size={16} />
          {data.warnings.join(" ")}{" "}
          {(data.truncated || data.has_more) &&
            "결과가 잘렸습니다. 경로 또는 깊이를 줄여 다시 생성하세요."}
        </div>
      )}
      {create.isError && (
        <div className="notice fail" role="alert">
          {text(create.error)}
        </div>
      )}
      <div className={`viewer selected-panel-${panels}`}>
        <aside className="explorer">
          <NodeExplorer
            key={data.diagram_id}
            graph={data}
            selected={selected}
            search={search}
            onSearch={setSearch}
            onSelect={setSelected}
          />
        </aside>
        <section className="canvas">
          <div className="canvas-toolbar">
            <b>{names[data.type]}</b>
            <span>노드 선택 / 드래그 / 확대·축소</span>
          </div>
          <div className="flow">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => setSelected(node.id)}
              fitView
              minZoom={0.15}
            >
              <Background color="var(--graph-dot)" gap={24} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="canvas-foot">
            <span>
              {isMock ? "예시 데이터 / 실제 분석 결과가 아닙니다" : "분석 결과"}
            </span>
            <span>
              {data.availability === "partial" ? "부분 지원" : "사용 가능"}
            </span>
          </div>
        </section>
        <aside className="details">
          <div className="panel-title">상세 정보</div>
          <div className="detail-body">
            {active ? (
              <>
                <span className="type-label">{active.type}</span>
                <h2>{active.label}</h2>
                <p className="path">{active.data.path}</p>
                {active.data.line && (
                  <p className="muted">라인 {active.data.line}</p>
                )}
                {fileId && (
                  <>
                    <p className="muted">파일 ID: {fileId}</p>
                    <button
                      className="outline"
                      onClick={() =>
                        create.mutate({
                          type: "symbols",
                          options: { file_id: fileId, max_nodes: 150 },
                        })
                      }
                    >
                      이 파일의 심볼 보기
                    </button>
                  </>
                )}
                {active.type === "directory" && (
                  <button
                    className="outline"
                    onClick={() =>
                      create.mutate({
                        type: "directory",
                        options: {
                          root_path: active.data.path ?? ".",
                          depth: 2,
                          max_nodes: 150,
                        },
                      })
                    }
                  >
                    이 폴더 열기
                  </button>
                )}
                <h3>연결된 관계</h3>
                {data.edges
                  .filter(
                    (e) => e.source === active.id || e.target === active.id,
                  )
                  .map((e) => (
                    <div className="detail-line" key={e.id}>
                      {e.type}:{" "}
                      <span>
                        {e.source === active.id ? e.target : e.source}
                      </span>
                    </div>
                  ))}
                {data.unresolved_references > 0 && (
                  <p className="muted">
                    미해결 참조 {data.unresolved_references}개는 가짜 연결을
                    만들지 않습니다.
                  </p>
                )}
                {active.data.github_url && !isMock ? (
                  <a
                    className="github"
                    href={active.data.github_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    GitHub 원본 보기 <ExternalLink size={14} />
                  </a>
                ) : (
                  <p className="detail-note">
                    {isMock
                      ? "예시 데이터에는 실제 원본 링크가 없습니다."
                      : "원본 링크를 제공하지 않습니다."}
                  </p>
                )}
              </>
            ) : (
              <p className="muted">노드를 선택하면 상세 정보가 표시됩니다.</p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

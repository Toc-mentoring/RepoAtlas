import { useCallback, useEffect, useMemo, useState } from "react";
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
  useNodesInitialized,
  useReactFlow,
  useStore,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { ExternalLink, AlertTriangle } from "lucide-react";
import { NodeExplorer } from "./NodeExplorer";
import { api, isMock } from "../../api/client";
import { Feedback } from "../../components/Feedback";
import { RunSearch } from "./RunSearch";
import { FilePicker } from "./FilePicker";
import { GraphFilters } from "./GraphFilters";
import {
  DiagramLegend,
  SpecialDetails,
  indexSchema,
  nodeMatches,
  safeSource,
  specialEdgeTypes,
  specialNodeTypes,
  type SchemaIndex,
} from "./SpecialDiagram";
import type { DiagramOptions, DiagramType, GraphDTO } from "../../api/types";
import "@xyflow/react/dist/style.css";
const names: Record<DiagramType, string> = {
  directory: "폴더 구조",
  dependency: "의존성",
  symbols: "심볼",
  architecture: "아키텍처",
  erd: "ERD",
};
const descriptions = {
  architecture: "설정에서 발견한 구성 요소와 의존 관계",
  erd: "SQL에서 발견한 테이블과 외래 키 관계",
};
export function DiagramChooser({ runId }: { runId: string }) {
  const [pickFile, setPickFile] = useState(false);
  const navigate = useNavigate();
  const catalog = useQuery({
    queryKey: ["catalog", runId],
    queryFn: () => api.getCatalog(runId),
  });
  const open = useMutation({
    mutationFn: async ({
      type,
      fileId,
    }: {
      type: DiagramType;
      fileId?: number;
    }) => {
      const options: DiagramOptions = {};
      if (type === "symbols") {
        options.file_id = fileId;
        options.max_nodes = 150;
      } else if (type === "directory" || type === "dependency") {
        options.root_path = ".";
        options.depth = 2;
        options.max_nodes = 150;
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
          확인할 다이어그램을 선택하세요. 심볼은 파일을 선택한 뒤 표시합니다.
        </p>
      </div>
      {catalog.isLoading && <p role="status">지원 유형을 불러오는 중입니다…</p>}
      {catalog.isError && (
        <Feedback
          error={catalog.error}
          retry={() => catalog.refetch()}
          runId={runId}
        />
      )}
      {catalog.data && (
        <div className="diagram-catalog">
          {catalog.data.items.map((item) => (
            <button
              key={item.type}
              disabled={item.availability === "unsupported" || open.isPending}
              onClick={() =>
                item.type === "symbols"
                  ? setPickFile(true)
                  : open.mutate({ type: item.type })
              }
              title={item.reason ?? undefined}
            >
              {names[item.type]}{" "}
              <small>
                {item.availability === "unsupported"
                  ? "미지원 · " + item.reason
                  : item.availability === "partial"
                    ? "부분 지원 · " + item.reason
                    : item.type === "architecture" || item.type === "erd"
                      ? descriptions[item.type]
                      : "바로 보기"}
              </small>
            </button>
          ))}
        </div>
      )}
      {pickFile && (
        <FilePicker
          runId={runId}
          pending={open.isPending}
          select={(fileId) => open.mutate({ type: "symbols", fileId })}
        />
      )}
      {!pickFile && <RunSearch runId={runId} />}
      {open.isPending && <p role="status">다이어그램을 불러오는 중입니다…</p>}
      {open.isError && <Feedback error={open.error} runId={runId} />}
    </section>
  );
}
function layout(
  graph: GraphDTO,
  schema?: SchemaIndex,
): { nodes: Node[]; edges: Edge[] } {
  const architecture = graph.type === "architecture";
  const special = architecture || !!schema;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: "LR",
    nodesep: special ? 54 : 35,
    ranksep: schema ? 68 : 95,
  });
  const visible = graph.nodes.filter(
    (node) => !schema?.tableByColumn.has(node.id),
  );
  for (const node of visible) {
    const columnCount = schema?.columnsByTable.get(node.id)?.length ?? 0;
    const size = schema
      ? { width: 252, height: 48 + columnCount * 37 }
      : architecture
        ? { width: 184, height: 72 }
        : { width: 180, height: 60 };
    g.setNode(node.id, size);
  }
  const links = graph.edges.flatMap((edge) => {
    const source = schema?.tableByColumn.get(edge.source)?.id ?? edge.source;
    const target = schema?.tableByColumn.get(edge.target)?.id ?? edge.target;
    if (schema && edge.type === "contains" && source === target) return [];
    if (source !== target || !schema) g.setEdge(source, target);
    return [{ edge, source, target }];
  });
  dagre.layout(g);
  return {
    nodes: visible.map((entry) => {
      const { x, y, width, height } = g.node(entry.id);
      const position = { x: x - width / 2, y: y - height / 2 };
      if (special)
        return {
          id: entry.id,
          position,
          width,
          type: architecture ? "architecture" : "schema",
          className: "diagram-node",
          focusable: false,
          selectable: false,
          data: {
            entry,
            columns: schema?.columnsByTable.get(entry.id),
            foreignKeySources: schema?.foreignKeySources,
          },
        };
      return {
        id: entry.id,
        position,
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        className: "file-node",
        data: {
          label: (
            <>
              <span className="node-icon">
                {entry.type === "directory" ? "▸" : "◇"}
              </span>
              <span>
                <strong>{entry.label}</strong>
                <small>{entry.data.path ?? entry.type}</small>
              </span>
            </>
          ),
        },
      };
    }),
    edges: links.map(({ edge, source, target }) => {
      const waypoints =
        schema && source !== target
          ? g.edge(source, target)?.points.slice(1, -1)
          : undefined;
      return {
        id: edge.id,
        source,
        target,
        ...(schema && {
          type:
            waypoints && waypoints.length > 1
              ? "routedForeignKey"
              : "smoothstep",
          sourceHandle: edge.source,
          targetHandle: source === target ? `self:${edge.target}` : edge.target,
        }),
        ...(special && { selectable: false, focusable: false }),
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--graph-edge)" },
        style: {
          stroke: "var(--graph-edge)",
          strokeWidth: 1.5,
          strokeDasharray:
            edge.data.certainty === "inferred" ? "6 4" : undefined,
        },
        data: { sourceId: edge.source, targetId: edge.target, waypoints },
      };
    }),
  };
}
type DiagramParent = {
  id: string;
  previous?: DiagramParent;
  maxNodes?: number;
};
type DiagramNavigation = {
  parent?: DiagramParent;
  focus?: { id: string; path: string };
  maxNodes?: number;
};
function FitGraph({
  revision,
  focus,
  compact,
}: {
  revision: string;
  focus: string | null;
  compact: boolean;
}) {
  const ready = useNodesInitialized();
  const { fitView } = useReactFlow();
  const width = useStore((state) => state.width);
  useEffect(() => {
    if (ready && width > 0)
      void fitView({
        padding: compact ? 0.12 : 0.2,
        minZoom: 0.02,
        maxZoom: 1,
        ...(focus ? { nodes: [{ id: focus }] } : {}),
      });
  }, [ready, width, revision, focus, compact, fitView]);
  return null;
}
export function GraphPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as DiagramNavigation | null;
  const { parent, focus, maxNodes } = state ?? {};
  const graph = useQuery({
    queryKey: ["diagram", id],
    queryFn: () => api.getDiagram(id),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [centered, setCentered] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  useEffect(() => {
    setSelected(focus?.id || null);
    setCentered(focus?.id || null);
    setSearch("");
    setPanels("graph");
    create.reset();
  }, [id]);
  const [panels, setPanels] = useState<"graph" | "tree" | "details">("graph");
  const selectNode = useCallback((nodeId: string, center = false) => {
    setSelected(nodeId);
    if (center) setCentered(nodeId);
    if (window.matchMedia("(max-width: 850px)").matches) setPanels("details");
  }, []);
  const create = useMutation({
    mutationFn: ({
      type,
      options,
    }: {
      type: DiagramType;
      options: DiagramOptions;
    }) => api.createDiagram(graph.data!.run_id, type, options),
    onSuccess: (data, { options }) => {
      if (data.diagram_id === id) {
        if (maxNodes !== options.max_nodes) {
          navigate(location.pathname, {
            replace: true,
            state: { ...state, maxNodes: options.max_nodes },
          });
        }
        return;
      }
      setSelected(null);
      navigate(`/diagrams/${data.diagram_id}`, {
        state: {
          parent: { id, previous: parent, maxNodes },
          maxNodes: options.max_nodes,
        },
      });
    },
  });
  const schema = useMemo(
    () => (graph.data?.type === "erd" ? indexSchema(graph.data) : undefined),
    [graph.data],
  );
  const special = graph.data?.type === "architecture" || !!schema;
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  useEffect(() => {
    const positions = graph.data
      ? layout(graph.data, schema)
      : { nodes: [], edges: [] };
    setNodes(positions.nodes);
    setEdges(positions.edges);
  }, [graph.data, schema, setNodes, setEdges]);
  const rendered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const entries =
      schema?.byId ?? new Map(graph.data?.nodes.map((node) => [node.id, node]));
    return {
      nodes: nodes.map((node) => {
        const entry = entries.get(node.id);
        const matching =
          !entry ||
          nodeMatches(entry, q) ||
          schema?.columnsByTable
            .get(node.id)
            ?.some((column) => nodeMatches(column, q));
        const active =
          node.id === selected ||
          schema?.tableByColumn.get(selected ?? "")?.id === node.id;
        return {
          ...node,
          selected: active,
          className: node.className + (matching || active ? "" : " dim"),
          data: special
            ? {
                ...node.data,
                query: q,
                selectedId: selected,
                onSelect: selectNode,
              }
            : node.data,
        };
      }),
      edges: edges.map((edge) => {
        const connected =
          selected === edge.source ||
          selected === edge.target ||
          selected === edge.data?.sourceId ||
          selected === edge.data?.targetId;
        return {
          ...edge,
          style: {
            ...edge.style,
            strokeWidth: connected ? 3 : 1.5,
            opacity: selected && !connected ? 0.3 : 1,
          },
        };
      }),
    };
  }, [nodes, edges, search, selected, graph.data, schema, special, selectNode]);
  if (graph.isLoading)
    return (
      <main className="home" role="status">
        다이어그램을 불러오는 중입니다…
      </main>
    );
  if (graph.isError || !graph.data)
    return (
      <main className="home">
        <Feedback error={graph.error} retry={() => graph.refetch()} />
        <Link to="/">저장소 목록</Link>
      </main>
    );
  const data = graph.data;
  const limited = data.truncated || data.has_more;
  const active = data.nodes.find((n) => n.id === selected);
  const sourceUrl =
    active?.data.github_url ??
    (active && schema?.tableByColumn.get(active.id)?.data.github_url);
  const focusId = special
    ? (schema?.tableByColumn.get(centered ?? "")?.id ?? centered)
    : selected;
  const summary = schema
    ? `테이블 ${data.nodes.filter((node) => node.type === "table").length}개 / 외래 키 연결 ${data.edges.filter((edge) => edge.type === "foreign_key").length}개`
    : `${special ? "구성 요소" : "노드"} ${data.nodes.length}개 / 관계 ${data.edges.length}개`;
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
              state={{ parent: parent.previous, maxNodes: parent.maxNodes }}
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
            {summary} {isMock ? "/ 예시 데이터" : ""}
          </p>
        </div>
        <div className="mobile-panels">
          <button
            aria-pressed={panels === "tree"}
            onClick={() => setPanels("tree")}
          >
            탐색기
          </button>
          <button
            aria-pressed={panels === "graph"}
            onClick={() => setPanels("graph")}
          >
            그래프
          </button>
          <button
            aria-pressed={panels === "details"}
            onClick={() => setPanels("details")}
          >
            상세
          </button>
        </div>
      </div>
      <div className="workspace-tools">
        {!special && (
          <details>
            <summary>분석 전체 검색</summary>
            <RunSearch runId={data.run_id} />
          </details>
        )}
        <GraphFilters
          key={data.diagram_id}
          graph={data}
          maxNodes={maxNodes}
          pending={create.isPending}
          apply={(options) => create.mutate({ type: data.type, options })}
        />
      </div>
      {focus && !data.nodes.some((n) => n.id === focus.id) && (
        <div className="notice" role="status">
          선택한 항목 {focus.path}이 서버의 표시 범위에 포함되지 않았습니다.
          최대 300개 노드 제한으로 전체 항목을 표시할 수 없는 경우입니다.
        </div>
      )}
      {data.availability === "partial" && (
        <div className="notice" role="status">
          부분 지원 다이어그램입니다. 경고와 근거를 확인해 주세요.
        </div>
      )}
      {(data.warnings.length > 0 || limited) && (
        <div className="notice">
          <AlertTriangle size={16} />
          {data.warnings.join(" ")}{" "}
          {limited &&
            (special
              ? maxNodes === 300
                ? "서버의 최대 표시 한도인 300개를 적용했습니다."
                : "그래프 범위·필터에서 최대 노드를 300개까지 늘릴 수 있습니다."
              : "결과가 잘렸습니다. 경로 또는 깊이를 줄여 다시 생성하세요.")}
        </div>
      )}
      {create.isError && <Feedback error={create.error} runId={data.run_id} />}
      {create.isPending && (
        <p className="workspace-tools" role="status">
          다이어그램을 불러오는 중입니다…
        </p>
      )}
      <div className={`viewer selected-panel-${panels}`}>
        <aside className="explorer">
          <NodeExplorer
            key={data.diagram_id}
            graph={data}
            selected={selected}
            search={search}
            onSearch={setSearch}
            onSelect={(nodeId) => selectNode(nodeId, true)}
            schema={schema}
          />
        </aside>
        <section className="canvas">
          <div className="canvas-toolbar">
            <b>{names[data.type]}</b>
            {special ? (
              <DiagramLegend schema={!!schema} />
            ) : (
              <span>노드 선택 / 드래그 / 확대·축소</span>
            )}
          </div>
          <div className="flow">
            {!data.nodes.length && (
              <p className="graph-empty" role="status">
                {schema
                  ? limited
                    ? "현재 표시 한도에 포함된 테이블이 없습니다."
                    : "분석에서 확인된 테이블이 없습니다."
                  : special
                    ? "분석에서 확인된 구성 요소가 없습니다."
                    : "현재 범위에 표시할 노드가 없습니다. 경로·언어·깊이 필터를 변경해 주세요."}
              </p>
            )}
            <ReactFlow
              key={data.diagram_id + panels}
              nodes={rendered.nodes}
              edges={rendered.edges}
              nodeTypes={specialNodeTypes}
              edgeTypes={specialEdgeTypes}
              deleteKeyCode={special ? null : undefined}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => selectNode(node.id)}
              fitView
              minZoom={0.02}
            >
              <FitGraph
                revision={data.diagram_id}
                focus={focusId}
                compact={!!schema}
              />
              <Background color="var(--graph-dot)" gap={24} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="canvas-foot">
            <span>
              {special
                ? schema
                  ? "SQL DDL 기반"
                  : "설정 파일 기반"
                : isMock
                  ? "예시 데이터 / 실제 분석 결과가 아닙니다"
                  : "분석 결과"}
            </span>
            <span>
              {data.availability === "partial"
                ? "부분 지원"
                : data.availability === "unsupported"
                  ? "미지원"
                  : "사용 가능"}
            </span>
          </div>
        </section>
        <aside className="details">
          <div className="panel-title">상세 정보</div>
          <div className="detail-body">
            {active ? (
              <>
                {special ? (
                  <SpecialDetails
                    graph={data}
                    node={active}
                    schema={schema}
                    isMock={isMock}
                    onSelect={(nodeId) => selectNode(nodeId, true)}
                  />
                ) : (
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
                          disabled={create.isPending}
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
                        disabled={create.isPending}
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
                          <small>
                            {e.data.certainty === "inferred"
                              ? "추론"
                              : "확인됨"}
                          </small>
                          {(e.data.evidence ?? []).map((ev, i) => (
                            <small key={i}>
                              {ev.path}
                              {ev.line ? `:${ev.line}` : ""} · {ev.basis}
                            </small>
                          ))}
                        </div>
                      ))}
                  </>
                )}
                {data.unresolved_references > 0 && (
                  <p className="muted">
                    미해결 참조 {data.unresolved_references}개
                  </p>
                )}
                {safeSource(sourceUrl) && !isMock ? (
                  <a
                    className="github"
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    GitHub 원본 보기 <ExternalLink size={14} />
                  </a>
                ) : (
                  !special && (
                    <p className="detail-note">
                      {isMock
                        ? "예시 데이터에는 실제 원본 링크가 없습니다."
                        : "원본 링크를 제공하지 않습니다."}
                    </p>
                  )
                )}
              </>
            ) : (
              <p className="muted">
                {schema
                  ? "테이블이나 컬럼을 선택하면 상세 정보가 표시됩니다."
                  : special
                    ? "구성 요소를 선택하면 관계와 근거가 표시됩니다."
                    : "노드를 선택하면 상세 정보가 표시됩니다."}
              </p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

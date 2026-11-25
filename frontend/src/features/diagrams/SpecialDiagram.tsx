import {
  BaseEdge,
  getSmoothStepPath,
  Handle,
  Position,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  ArrowRight,
  Blocks,
  Database,
  ExternalLink,
  Table2,
} from "lucide-react";
import type { DiagramEdge, DiagramNode, GraphDTO } from "../../api/types";

const componentKinds: Record<string, string> = {
  frontend: "프론트엔드",
  backend: "백엔드",
  worker: "워커",
  database: "데이터베이스",
  service: "서비스",
  framework: "프레임워크",
  package: "JavaScript 앱",
  fastapi_app: "FastAPI 앱",
  dockerfile: "Dockerfile",
};

export function componentKind(node: DiagramNode) {
  const kind = node.data.kind;
  return typeof kind === "string"
    ? (componentKinds[kind] ?? kind)
    : "구성 요소";
}

export function nodeMatches(node: DiagramNode, query: string) {
  return (
    !query ||
    [
      node.label,
      node.data.path,
      node.data.technology,
      schemaName(node),
      node.data.frameworks,
      node.data.data_type,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query)
  );
}

export function indexSchema(graph: GraphDTO) {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const tableByColumn = new Map<string, DiagramNode>();
  const columnsByTable = new Map<string, DiagramNode[]>();
  const foreignKeySources = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.type === "foreign_key") foreignKeySources.add(edge.source);
    if (edge.type !== "contains") continue;
    const table = byId.get(edge.source);
    const column = byId.get(edge.target);
    if (
      table?.type !== "table" ||
      column?.type !== "column" ||
      tableByColumn.has(column.id)
    )
      continue;
    tableByColumn.set(column.id, table);
    const columns = columnsByTable.get(table.id) ?? [];
    columns.push(column);
    columnsByTable.set(table.id, columns);
  }
  for (const columns of columnsByTable.values()) {
    columns.sort(
      (a, b) =>
        ordinal(a.data.ordinal_position) - ordinal(b.data.ordinal_position),
    );
  }
  return { byId, tableByColumn, columnsByTable, foreignKeySources };
}

export type SchemaIndex = ReturnType<typeof indexSchema>;

function ordinal(value: unknown) {
  return typeof value === "number" ? value : Number.MAX_SAFE_INTEGER;
}

function schemaName(node: DiagramNode) {
  const name = node.data.schema ?? node.data.schema_name;
  return typeof name === "string" ? name : undefined;
}

function columnType(node: DiagramNode) {
  return typeof node.data.data_type === "string"
    ? node.data.data_type
    : undefined;
}

function columnKeys(node: DiagramNode, foreignKey: boolean) {
  return [node.data.is_primary === true && "PK", foreignKey && "FK"]
    .filter(Boolean)
    .join(" / ");
}

function ColumnKeys({
  node,
  foreignKey,
}: {
  node: DiagramNode;
  foreignKey: boolean;
}) {
  const keys = columnKeys(node, foreignKey);
  return (
    <span className="column-keys" title={keys || undefined}>
      {keys}
    </span>
  );
}

type DiagramNodeData = {
  entry: DiagramNode;
  columns?: DiagramNode[];
  foreignKeySources?: Set<string>;
  query?: string;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
};

function ArchitectureNode({
  data,
  selected,
}: NodeProps<Node<DiagramNodeData>>) {
  const { entry, onSelect } = data;
  const Icon = entry.data.kind === "database" ? Database : Blocks;
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button
        type="button"
        className="architecture-node-button nopan"
        aria-pressed={selected}
        onClick={(event) => {
          event.stopPropagation();
          onSelect?.(entry.id);
        }}
      >
        <Icon size={20} aria-hidden="true" />
        <span>
          <strong title={entry.label}>{entry.label}</strong>
          <small title={componentKind(entry)}>{componentKind(entry)}</small>
        </span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </>
  );
}

function PortPair({ id }: { id: string }) {
  return (
    <>
      <Handle
        id={id}
        type="target"
        position={Position.Left}
        isConnectable={false}
      />
      <Handle
        id={id}
        type="source"
        position={Position.Right}
        isConnectable={false}
      />
      <Handle
        id={`self:${id}`}
        type="target"
        position={Position.Right}
        isConnectable={false}
      />
    </>
  );
}

function SchemaNode({ data }: NodeProps<Node<DiagramNodeData>>) {
  const {
    entry,
    columns = [],
    foreignKeySources,
    query = "",
    selectedId,
    onSelect,
  } = data;
  const schema = schemaName(entry);
  return (
    <>
      <div className="schema-node-head">
        <PortPair id={entry.id} />
        <button
          type="button"
          className="nopan"
          aria-pressed={entry.id === selectedId}
          onClick={(event) => {
            event.stopPropagation();
            onSelect?.(entry.id);
          }}
        >
          <Table2 size={16} aria-hidden="true" />
          <strong title={entry.label}>{entry.label}</strong>
          <small title={schema ?? columnType(entry)}>
            {schema ?? columnType(entry)}
          </small>
        </button>
      </div>
      {columns.map((column) => (
        <div className="schema-node-row" key={column.id}>
          <PortPair id={column.id} />
          <button
            type="button"
            className={`nodrag nopan${!nodeMatches(entry, query) && !nodeMatches(column, query) && selectedId !== column.id ? " dim" : ""}`}
            aria-pressed={column.id === selectedId}
            onClick={(event) => {
              event.stopPropagation();
              onSelect?.(column.id);
            }}
          >
            <ColumnKeys
              node={column}
              foreignKey={foreignKeySources?.has(column.id) ?? false}
            />
            <span title={column.label}>{column.label}</span>
            <small title={columnType(column)}>{columnType(column)}</small>
          </button>
        </div>
      ))}
    </>
  );
}

export const specialNodeTypes = {
  architecture: ArchitectureNode,
  schema: SchemaNode,
};

function RoutedForeignKey(
  props: EdgeProps<Edge<{ waypoints?: { x: number; y: number }[] }>>,
) {
  const { id, data, sourceX, sourceY, targetX, targetY, markerEnd, style } =
    props;
  const points = data?.waypoints ?? [];
  const first = points[0];
  const last = points[points.length - 1];
  // Dagre reserves space around intervening tables for edges that span several ranks.
  const path =
    first && last && sourceX < first.x && last.x < targetX
      ? `M ${sourceX} ${sourceY} H ${first.x} ${points.map(({ x, y }) => `L ${x} ${y}`).join(" ")} V ${targetY} H ${targetX}`
      : getSmoothStepPath(props)[0];
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
}

export const specialEdgeTypes = { routedForeignKey: RoutedForeignKey };

export function safeSource(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return (
      url.origin === "https://github.com" &&
      !url.username &&
      !url.password &&
      /^\/[^/]+\/[^/]+\/(blob|tree)\/[a-f0-9]{40}\//i.test(url.pathname)
    );
  } catch {
    return false;
  }
}

export function DiagramLegend({ schema }: { schema: boolean }) {
  return (
    <ul className="diagram-legend" aria-label="범례">
      {schema ? (
        <>
          <li>
            <abbr title="Primary key">PK</abbr> 기본 키
          </li>
          <li>
            <abbr title="Foreign key">FK</abbr> 외래 키
          </li>
        </>
      ) : (
        <>
          <li>
            <span aria-hidden="true" /> 확인된 관계
          </li>
          <li>
            <span className="inferred" aria-hidden="true" /> 추론된 관계
          </li>
        </>
      )}
    </ul>
  );
}

export function SpecialDetails({
  graph,
  node,
  schema,
  isMock,
  onSelect,
}: {
  graph: GraphDTO;
  node: DiagramNode;
  schema?: SchemaIndex;
  isMock: boolean;
  onSelect: (id: string) => void;
}) {
  const table = schema?.tableByColumn.get(node.id);
  const columns = schema?.columnsByTable.get(node.id) ?? [];
  const nodes =
    schema?.byId ?? new Map(graph.nodes.map((entry) => [entry.id, entry]));
  const endpoint = (id: string) => {
    const parent = schema?.tableByColumn.get(id);
    const label = nodes.get(id)?.label ?? id;
    return parent ? `${parent.label}.${label}` : label;
  };
  const relatesToNode = (id: string) =>
    id === node.id || schema?.tableByColumn.get(id)?.id === node.id;
  const groups = new Map<string, DiagramEdge[]>();
  for (const edge of graph.edges) {
    if (schema && edge.type !== "foreign_key") continue;
    const constraint = edge.data.constraint_name;
    const key =
      schema && typeof constraint === "string" && constraint
        ? `${schema.tableByColumn.get(edge.source)?.id ?? edge.source}:${constraint}`
        : edge.id;
    const group = groups.get(key) ?? [];
    group.push(edge);
    groups.set(key, group);
  }
  const relatedGroups = [...groups].filter(([, group]) =>
    group.some(
      (edge) => relatesToNode(edge.source) || relatesToNode(edge.target),
    ),
  );
  const kind = schema
    ? node.type === "table"
      ? "테이블"
      : "컬럼"
    : componentKind(node);
  const technology =
    typeof node.data.technology === "string"
      ? node.data.technology
      : Array.isArray(node.data.frameworks)
        ? node.data.frameworks
            .filter((name) => typeof name === "string")
            .join(", ")
        : undefined;
  const evidence = Array.isArray(node.data.evidence)
    ? node.data.evidence[0]
    : undefined;
  const path = node.data.path ?? table?.data.path;
  const line = node.data.line ?? evidence?.line;
  const tableSchema = schemaName(node);
  return (
    <>
      <span className="type-label">{kind}</span>
      <h2>{node.label}</h2>
      {path && (
        <p className="path">
          {path}
          {typeof line === "number" ? `:${line}` : ""}
        </p>
      )}
      <dl className="diagram-fields">
        {technology && (
          <>
            <dt>기술</dt>
            <dd>{technology}</dd>
          </>
        )}
        {tableSchema && (
          <>
            <dt>스키마</dt>
            <dd>{tableSchema}</dd>
          </>
        )}
        {table && (
          <>
            <dt>테이블</dt>
            <dd>
              <button
                type="button"
                className="diagram-text-button"
                onClick={() => onSelect(table.id)}
              >
                {table.label}
              </button>
            </dd>
          </>
        )}
        {columnType(node) && (
          <>
            <dt>데이터 타입</dt>
            <dd>{columnType(node)}</dd>
          </>
        )}
        {schema &&
          node.type === "column" &&
          columnKeys(node, schema.foreignKeySources.has(node.id)) && (
            <>
              <dt>키</dt>
              <dd>{columnKeys(node, schema.foreignKeySources.has(node.id))}</dd>
            </>
          )}
        {typeof node.data.is_nullable === "boolean" && (
          <>
            <dt>NULL</dt>
            <dd>{node.data.is_nullable ? "허용" : "허용 안 함"}</dd>
          </>
        )}
      </dl>
      {schema && node.type === "table" && (
        <>
          <h3>컬럼 {columns.length}개</h3>
          {columns.length ? (
            <ul className="detail-column-list">
              {columns.map((column) => (
                <li key={column.id}>
                  <button type="button" onClick={() => onSelect(column.id)}>
                    <ColumnKeys
                      node={column}
                      foreignKey={schema.foreignKeySources.has(column.id)}
                    />
                    <span>{column.label}</span>
                    <small>{columnType(column)}</small>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="detail-note">표시할 컬럼이 없습니다.</p>
          )}
        </>
      )}
      <h3>{schema ? "외래 키 관계" : "연결된 관계"}</h3>
      {relatedGroups.length === 0 && (
        <p className="detail-note">연결된 관계가 없습니다.</p>
      )}
      {relatedGroups.map(([key, group]) => (
        <div className="diagram-relation" key={key}>
          {schema && group[0].data.constraint_name && (
            <strong>{group[0].data.constraint_name}</strong>
          )}
          {group
            .sort(
              (a, b) =>
                ordinal(a.data.ordinal_position) -
                ordinal(b.data.ordinal_position),
            )
            .map((edge) => (
              <div className="diagram-relation-item" key={edge.id}>
                {!schema && edge.data.certainty && (
                  <span className="type-label">
                    {edge.data.certainty === "inferred" ? "추론" : "확인됨"}
                  </span>
                )}
                <div className="diagram-relation-ends">
                  <button
                    type="button"
                    className="diagram-text-button"
                    onClick={() => onSelect(edge.source)}
                  >
                    {endpoint(edge.source)}
                  </button>
                  <ArrowRight size={13} aria-label="참조" />
                  <button
                    type="button"
                    className="diagram-text-button"
                    onClick={() => onSelect(edge.target)}
                  >
                    {endpoint(edge.target)}
                  </button>
                </div>
                {(edge.data.evidence ?? []).map((evidence, index) => {
                  const location = evidence.path
                    ? `${evidence.path}${evidence.line ? `:${evidence.line}` : ""}`
                    : undefined;
                  return (
                    <div className="diagram-evidence" key={index}>
                      {location &&
                      !isMock &&
                      safeSource(evidence.github_url) ? (
                        <a
                          href={evidence.github_url}
                          target="_blank"
                          rel="noreferrer"
                          className="path"
                        >
                          {location}{" "}
                          <ExternalLink size={12} aria-hidden="true" />
                        </a>
                      ) : (
                        location && <span className="path">{location}</span>
                      )}
                      <small>{evidence.basis}</small>
                    </div>
                  );
                })}
              </div>
            ))}
        </div>
      ))}
    </>
  );
}

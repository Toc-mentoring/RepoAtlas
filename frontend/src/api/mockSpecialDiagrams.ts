import type { DiagramEdge, DiagramNode } from "./types";

const compose = "compose.yml";
const components: DiagramNode[] = [
  {
    id: "component:web",
    type: "component",
    label: "web",
    data: { kind: "frontend", technology: "React", path: compose, line: 2 },
  },
  {
    id: "component:api",
    type: "component",
    label: "api",
    data: { kind: "backend", technology: "FastAPI", path: compose, line: 7 },
  },
  {
    id: "component:worker",
    type: "component",
    label: "worker",
    data: { kind: "worker", technology: "Python", path: compose, line: 13 },
  },
  {
    id: "component:db",
    type: "component",
    label: "db",
    data: {
      kind: "database",
      technology: "PostgreSQL",
      path: compose,
      line: 18,
    },
  },
];

function dependency(
  source: string,
  target: string,
  line: number,
  certainty: "confirmed" | "inferred",
  path = compose,
): DiagramEdge {
  return {
    id: `architecture_dependency:${source}:${target}`,
    source: `component:${source}`,
    target: `component:${target}`,
    type: "architecture_dependency",
    data: {
      certainty,
      evidence: [
        {
          path,
          line,
          basis:
            certainty === "confirmed" ? "compose_depends_on" : "api_base_url",
        },
      ],
    },
  };
}

export const architectureExample = {
  nodes: components,
  edges: [
    dependency("web", "api", 8, "inferred", "frontend/src/api.ts"),
    dependency("api", "db", 11, "confirmed"),
    dependency("worker", "db", 16, "confirmed"),
  ],
};

const ddl = "db/schema.sql";
const schema = [
  {
    name: "users",
    line: 1,
    columns: [
      ["id", "bigint"],
      ["email", "text"],
      ["created_at", "timestamptz"],
    ],
  },
  {
    name: "projects",
    line: 7,
    columns: [
      ["id", "bigint"],
      ["owner_id", "bigint"],
      ["name", "text"],
    ],
  },
  {
    name: "tasks",
    line: 13,
    columns: [
      ["id", "bigint"],
      ["project_id", "bigint"],
      ["assignee_id", "bigint"],
      ["parent_id", "bigint"],
      ["title", "text"],
      ["completed_at", "timestamptz"],
    ],
  },
];

function foreignKey(source: string, target: string, line: number): DiagramEdge {
  return {
    id: `foreign_key:${source}:${target}`,
    source: `column:${source}`,
    target: `column:${target}`,
    type: "foreign_key",
    data: {
      certainty: "confirmed",
      constraint_name: `${source.replace(".", "_")}_fkey`,
      ordinal_position: 1,
      evidence: [{ path: ddl, line, basis: "sql_ddl_foreign_key" }],
    },
  };
}

export const erdExample: { nodes: DiagramNode[]; edges: DiagramEdge[] } = {
  nodes: schema.flatMap(({ name, line, columns }) => [
    {
      id: `table:${name}`,
      type: "table",
      label: name,
      data: { schema: "public", path: ddl, line },
    },
    ...columns.map(([column, dataType], index) => ({
      id: `column:${name}.${column}`,
      type: "column",
      label: column,
      data: {
        data_type: dataType,
        ordinal_position: index + 1,
        is_primary: index === 0,
        is_nullable: ["assignee_id", "parent_id", "completed_at"].includes(
          column,
        ),
        path: ddl,
        line: line + index + 1,
      },
    })),
  ]),
  edges: [
    ...schema.flatMap(({ name, columns }) =>
      columns.map(([column]) => ({
        id: `contains:${name}:${column}`,
        source: `table:${name}`,
        target: `column:${name}.${column}`,
        type: "contains",
        data: {},
      })),
    ),
    foreignKey("projects.owner_id", "users.id", 9),
    foreignKey("tasks.project_id", "projects.id", 15),
    foreignKey("tasks.assignee_id", "users.id", 16),
    foreignKey("tasks.parent_id", "tasks.id", 17),
  ],
};

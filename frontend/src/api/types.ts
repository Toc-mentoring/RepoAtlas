export type DiagramType =
  | "directory"
  | "dependency"
  | "symbols"
  | "architecture"
  | "erd";
export type Availability = "available" | "partial" | "unsupported";
export type DiagramOptions = {
  root_path?: string;
  depth?: number;
  max_nodes?: number;
  language?: string;
  file_id?: number;
};
export type DiagramNode = {
  id: string;
  type: string;
  label: string;
  data: {
    path?: string;
    language?: string;
    line?: number;
    github_url?: string;
    [key: string]: unknown;
  };
};
export type DiagramEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  data: {
    certainty?: "confirmed" | "inferred";
    evidence?: {
      path: string | null;
      line?: number | null;
      basis: string;
      github_url?: string | null;
    }[];
    constraint_name?: string;
    ordinal_position?: number;
  };
};
export type GraphDTO = {
  diagram_id: string;
  run_id: string;
  type: DiagramType;
  availability: Availability;
  truncated: boolean;
  has_more: boolean;
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  warnings: string[];
  unresolved_references: number;
};
export type Catalog = {
  run_id: string;
  items: {
    type: DiagramType;
    availability: Availability;
    reason: string | null;
  }[];
};

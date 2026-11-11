import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  Folder,
  FolderOpen,
  Search,
} from "lucide-react";
import type { DiagramNode, GraphDTO } from "../../api/types";

type Item = {
  key: string;
  label: string;
  node?: DiagramNode;
  children: Item[];
};
const categoryNames: Record<string, string> = {
  directory: "폴더",
  file: "파일",
  function: "함수",
  class: "클래스",
  method: "메서드",
  interface: "인터페이스",
  component: "구성 요소",
  table: "테이블",
  column: "컬럼",
};
function label(type: string) {
  return categoryNames[type] ?? type;
}

// Folder paths provide structure even when a dependency graph contains only file nodes.
function buildTree(graph: GraphDTO): Item[] {
  const directories = new Map<string, Item>();
  const roots: Item[] = [];
  const entries = new Map<string, Item>();
  const normalize = (p: string) =>
    p.replace(/^\.\//, "").replace(/\/$/, "") || ".";
  const ensure = (raw: string): Item => {
    const path = normalize(raw);
    const found = directories.get(path);
    if (found) return found;
    const item: Item = {
      key: `path:${path}`,
      label: path === "." ? "저장소" : path.split("/").pop()!,
      children: [],
    };
    directories.set(path, item);
    if (path === ".") roots.push(item);
    else {
      const slash = path.lastIndexOf("/");
      const parent = slash < 0 ? "." : path.slice(0, slash);
      ensure(parent).children.push(item);
    }
    return item;
  };
  for (const node of graph.nodes) {
    if (node.type === "directory" && node.data.path) {
      const dir = ensure(node.data.path);
      dir.node = node;
      dir.label = node.label;
      entries.set(node.id, dir);
    }
  }
  for (const node of graph.nodes) {
    if (node.type === "directory" && node.data.path) continue;
    const item: Item = {
      key: `node:${node.id}`,
      label: node.label,
      node,
      children: [],
    };
    entries.set(node.id, item);
  }
  const parentEdges = new Map<string, string>();
  for (const edge of graph.edges) {
    if (
      (edge.type === "contains" || edge.type === "declares") &&
      entries.has(edge.source) &&
      entries.has(edge.target) &&
      edge.source !== edge.target &&
      !parentEdges.has(edge.target)
    )
      parentEdges.set(edge.target, edge.source);
  }
  for (const node of graph.nodes) {
    const item = entries.get(node.id)!;
    if (node.type === "directory" && node.data.path) continue;
    const parentId = parentEdges.get(node.id);
    const parent = parentId ? entries.get(parentId) : undefined;
    if (parent && parent !== item) {
      parent.children.push(item);
      continue;
    }
    if (node.data.path) {
      const path = normalize(node.data.path);
      const slash = path.lastIndexOf("/");
      ensure(slash < 0 ? "." : path.slice(0, slash)).children.push(item);
    } else roots.push(item);
  }
  const sort = (items: Item[]) => {
    items.sort(
      (a, b) =>
        Number(b.children.length > 0 || b.node?.type === "directory") -
          Number(a.children.length > 0 || a.node?.type === "directory") ||
        a.label.localeCompare(b.label),
    );
    items.forEach((x) => sort(x.children));
  };
  sort(roots);
  return roots;
}
export function NodeExplorer({
  graph,
  selected,
  search,
  onSearch,
  onSelect,
}: {
  graph: GraphDTO;
  selected: string | null;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
}) {
  const tree = useMemo(() => buildTree(graph), [graph]);
  const types = useMemo(
    () => Array.from(new Set(graph.nodes.map((n) => n.type))).sort(),
    [graph],
  );
  const [category, setCategory] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(["path:."]),
  );
  const query = search.trim().toLowerCase();
  const matches = (item: Item) =>
    !!item.node &&
    (category === "all" || item.node.type === category) &&
    (!query ||
      `${item.node.label} ${item.node.data.path ?? ""}`
        .toLowerCase()
        .includes(query));
  const containsMatch = (item: Item): boolean =>
    matches(item) || item.children.some(containsMatch);
  const filterActive = !!query || category !== "all";
  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const renderItem = (item: Item, depth: number): React.ReactNode => {
    if (filterActive && !containsMatch(item)) return null;
    const branch = item.children.length > 0 || item.node?.type === "directory";
    const open = filterActive
      ? !expanded.has(`closed:${item.key}`)
      : expanded.has(item.key);
    const flip = () =>
      filterActive ? toggle(`closed:${item.key}`) : toggle(item.key);
    return (
      <div key={item.key}>
        <div
          className={`explorer-row ${selected === item.node?.id && item.node ? "active" : ""}`}
          style={{ paddingLeft: 8 + depth * 16 }}
        >
          {branch ? (
            <button
              className="tree-toggle"
              type="button"
              onClick={flip}
              aria-label={`${item.label} ${open ? "접기" : "펼치기"}`}
              aria-expanded={open}
            >
              {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
          ) : (
            <span className="tree-toggle-placeholder" />
          )}
          {item.node ? (
            <button
              className="tree-label"
              type="button"
              onClick={() => onSelect(item.node!.id)}
              title={item.node.data.path ?? item.label}
            >
              {branch ? (
                open ? (
                  <FolderOpen size={15} />
                ) : (
                  <Folder size={15} />
                )
              ) : (
                <FileCode2 size={15} />
              )}
              <span>{item.label}</span>
            </button>
          ) : (
            <button className="tree-label" type="button" onClick={flip}>
              {open ? <FolderOpen size={15} /> : <Folder size={15} />}
              <span>{item.label}</span>
            </button>
          )}
        </div>
        {branch &&
          open &&
          item.children.map((child) => renderItem(child, depth + 1))}
      </div>
    );
  };
  return (
    <>
      <div className="panel-title">
        탐색기 <span>{graph.nodes.length}개</span>
      </div>
      <div className="search">
        <Search size={15} />
        <input
          aria-label="노드 검색"
          placeholder="노드 검색"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>
      <label className="explorer-filter">
        종류
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="노드 종류"
        >
          <option value="all">전체</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {label(type)}
            </option>
          ))}
        </select>
      </label>
      <div className="explorer-tree">
        {tree.some((item) => !filterActive || containsMatch(item)) ? (
          tree.map((item) => renderItem(item, 0))
        ) : (
          <p className="empty">일치하는 항목이 없습니다.</p>
        )}
      </div>
      <div className="explorer-foot">
        {graph.unresolved_references}개 미해결 참조
      </div>
    </>
  );
}

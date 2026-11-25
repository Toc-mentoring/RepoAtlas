import { useState } from "react";
import type { DiagramOptions, GraphDTO } from "../../api/types";

export function GraphFilters({
  graph,
  pending,
  apply,
}: {
  graph: GraphDTO;
  pending: boolean;
  apply: (options: DiagramOptions) => void;
}) {
  const [path, setPath] = useState(".");
  const [depth, setDepth] = useState(2);
  const [limit, setLimit] = useState(150);
  const [language, setLanguage] = useState("");
  const [error, setError] = useState("");
  const scoped = graph.type === "directory" || graph.type === "dependency";
  const file = graph.nodes.find((n) => n.type === "file");
  if (!scoped && graph.type !== "symbols") return null;
  return (
    <details className="graph-filters">
      <summary>그래프 범위·필터</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const normalized =
            path.trim().replace(/^\.\//, "").replace(/\/$/, "") || ".";
          if (
            normalized.startsWith("/") ||
            normalized.includes("\\") ||
            normalized.split("/").includes("..")
          ) {
            setError(
              "저장소 상대경로를 입력해 주세요. '..'는 사용할 수 없습니다.",
            );
            return;
          }
          setError("");
          apply(
            scoped
              ? {
                  root_path: normalized,
                  depth,
                  max_nodes: limit,
                  ...(graph.type === "dependency" && language
                    ? { language }
                    : {}),
                }
              : { file_id: Number(file?.id.slice(5)), max_nodes: limit },
          );
        }}
      >
        {scoped && (
          <>
            <label>
              폴더 경로
              <input
                aria-label="폴더 경로"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder=". 또는 src"
                required
              />
            </label>
            <label>
              깊이
              <input
                aria-label="그래프 깊이"
                type="number"
                min={1}
                max={8}
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
                required
              />
            </label>
          </>
        )}
        {graph.type === "dependency" && (
          <label>
            언어
            <select
              aria-label="의존성 언어"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="">전체</option>
              {["python", "javascript", "typescript", "jsx", "tsx"].map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          최대 노드
          <input
            aria-label="최대 노드"
            type="number"
            min={20}
            max={300}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            required
          />
        </label>
        <button className="outline" disabled={pending || (!scoped && !file)}>
          {pending ? "적용 중…" : "필터 적용"}
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>
    </details>
  );
}

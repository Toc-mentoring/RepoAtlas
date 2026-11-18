import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type SearchItem } from "../../api/client";
import { nextPage, pageItems } from "../../api/pages";
import { Feedback, MoreButton } from "../../components/Feedback";

export const parentPath = (path: string) =>
  path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ".";

// Search returns a symbol ID, not its file ID. Resolve the exact path through A07.
export async function fileForPath(runId: string, path: string) {
  let cursor: string | null = null;
  const seen = new Set<string>();
  do {
    const result = await api.listNodes(runId, {
      root_path: parentPath(path),
      depth: 1,
      limit: 100,
      cursor,
    });
    const file = result.items.find((n) => n.kind === "file" && n.path === path);
    if (file) return file.id;
    cursor = result.next_cursor;
    if (cursor && seen.has(cursor)) break;
    if (cursor) seen.add(cursor);
  } while (cursor);
  throw new Error(
    "검색한 파일을 찾을 수 없습니다. 분석 결과를 새로고침해 주세요.",
  );
}

export function RunSearch({
  runId,
  onFile,
  disabled = false,
}: {
  runId: string;
  onFile?: (fileId: number) => void;
  disabled?: boolean;
}) {
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    const timer = setTimeout(() => setQ(input.trim()), 300);
    return () => clearTimeout(timer);
  }, [input]);
  const valid = q === input.trim() && q.length >= 2 && q.length <= 100;
  const results = useInfiniteQuery({
    queryKey: ["search", runId, q],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.search(runId, q, { cursor: pageParam }),
    getNextPageParam: nextPage,
    enabled: valid,
    retry: false,
  });
  const open = useMutation({
    mutationFn: async (item: SearchItem) => {
      const fileId =
        item.kind === "file"
          ? Number(item.id.slice(5))
          : await fileForPath(runId, item.path);
      if (onFile) {
        onFile(fileId);
        return;
      }
      const data = await api.createDiagram(
        runId,
        item.kind === "symbol" ? "symbols" : "directory",
        item.kind === "symbol"
          ? { file_id: fileId, max_nodes: 300 }
          : { root_path: parentPath(item.path), depth: 1, max_nodes: 300 },
      );
      navigate(`/diagrams/${data.diagram_id}`, {
        state: { focus: { id: item.id, path: item.path } },
      });
    },
  });
  const items = pageItems(results.data?.pages);
  return (
    <section className="run-search" aria-label="분석 전체 검색">
      <label>
        분석 전체 검색
        <input
          aria-label="분석 전체 검색"
          placeholder="파일·심볼 이름을 2자 이상 입력"
          value={input}
          maxLength={100}
          onChange={(e) => {
            setInput(e.target.value);
            open.reset();
          }}
        />
      </label>
      {input.trim().length === 1 && (
        <small>검색어는 2자 이상 입력해 주세요.</small>
      )}
      {valid && results.isLoading && <p role="status">검색 중…</p>}
      {valid && results.isError && (
        <Feedback
          error={results.error}
          retry={() =>
            results.isFetchNextPageError
              ? results.fetchNextPage()
              : results.refetch()
          }
          runId={runId}
        />
      )}
      {valid && results.isSuccess && !items.length && (
        <p className="empty">검색 결과가 없습니다.</p>
      )}
      {valid && items.length > 0 && (
        <ul className="search-results">
          {items.map((item) => (
            <li key={item.id}>
              <button
                disabled={open.isPending || disabled}
                onClick={() => open.mutate(item)}
              >
                <b>{item.label}</b>
                <small>
                  {item.kind === "symbol" ? "심볼" : "파일"} · {item.path}
                  {item.line ? `:${item.line}` : ""}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {valid && (
        <MoreButton
          more={!!results.hasNextPage}
          pending={results.isFetching}
          load={() => results.fetchNextPage()}
        />
      )}
      {open.isPending && <p role="status">선택한 항목을 여는 중입니다…</p>}
      {open.isError && <Feedback error={open.error} runId={runId} />}
    </section>
  );
}

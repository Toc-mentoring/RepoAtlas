import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { nextPage } from "../../api/pages";
import { Feedback, MoreButton } from "../../components/Feedback";
import { RunSearch } from "./RunSearch";

export function FilePicker({
  runId,
  pending,
  select,
}: {
  runId: string;
  pending: boolean;
  select: (id: number) => void;
}) {
  const files = useInfiniteQuery({
    queryKey: ["files", runId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.listNodes(runId, { cursor: pageParam }),
    getNextPageParam: nextPage,
    retry: false,
  });
  const items = Array.from(
    new Map(
      files.data?.pages
        .flatMap((p) => p.items)
        .filter((n) => n.kind === "file")
        .map((n) => [n.id, n]),
    ).values(),
  );
  return (
    <section className="file-picker">
      <h2>심볼을 확인할 파일 선택</h2>
      <RunSearch runId={runId} onFile={select} disabled={pending} />
      <p className="muted">
        목록은 루트에서 깊이 8까지 표시합니다. 더 깊은 파일은 분석 전체 검색으로
        찾으세요.
      </p>
      {files.isLoading && <p role="status">파일을 불러오는 중입니다…</p>}
      {files.isError && (
        <Feedback
          error={files.error}
          retry={() =>
            files.isFetchNextPageError ? files.fetchNextPage() : files.refetch()
          }
          runId={runId}
        />
      )}
      {files.isSuccess && !items.length && (
        <p>
          현재 페이지에 파일이 없습니다. 다음 페이지 또는 검색을 이용하세요.
        </p>
      )}
      <ul className="search-results">
        {items.map((n) => (
          <li key={n.id}>
            <button disabled={pending} onClick={() => select(n.id)}>
              {n.path}
            </button>
          </li>
        ))}
      </ul>
      <MoreButton
        more={!!files.hasNextPage}
        pending={files.isFetching}
        load={() => files.fetchNextPage()}
      />
    </section>
  );
}

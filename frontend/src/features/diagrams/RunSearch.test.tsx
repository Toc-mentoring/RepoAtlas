// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import { RunSearch } from "./RunSearch";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function Location() {
  const l = useLocation();
  return (
    <output>
      {l.pathname} {JSON.stringify(l.state)}
    </output>
  );
}
it("현재 그래프 밖의 심볼을 검색하고 정확한 파일의 심볼 그래프로 이동한다", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    items: [
      {
        kind: "symbol",
        id: "symbol:900",
        label: "HiddenFunction",
        path: "deep/nested/hidden.py",
        line: 42,
      },
    ],
    next_cursor: null,
  });
  const list = vi
    .spyOn(api, "listNodes")
    .mockResolvedValueOnce({ items: [], next_cursor: "next-sibling" })
    .mockResolvedValueOnce({
      items: [
        {
          id: 88,
          parent_id: 1,
          kind: "file",
          name: "hidden.py",
          path: "deep/nested/hidden.py",
          language: "python",
          parse_status: "parsed",
        },
      ],
      next_cursor: null,
    });
  const create = vi
    .spyOn(api, "createDiagram")
    .mockResolvedValue({ diagram_id: "found-graph" } as any);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RunSearch runId="run-1" />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "분석 전체 검색" }), {
    target: { value: "Hidden" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: /HiddenFunction/ }),
  );
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith("run-1", "symbols", {
      file_id: 88,
      max_nodes: 300,
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("status").textContent).toContain(
      "/diagrams/found-graph",
    ),
  );
  expect(screen.getByRole("status").textContent).toContain("symbol:900");
  expect(list).toHaveBeenLastCalledWith("run-1", {
    root_path: "deep/nested",
    depth: 1,
    limit: 100,
    cursor: "next-sibling",
  });
  client.clear();
});
it("한 글자 검색은 API에 보내지 않고 실패를 빈 검색 결과와 구분한다", async () => {
  const search = vi
    .spyOn(api, "search")
    .mockRejectedValue(new Error("검색 연결 실패"));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RunSearch runId="run-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const input = screen.getByRole("textbox", { name: "분석 전체 검색" });
  fireEvent.change(input, { target: { value: "a" } });
  expect(search).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "api" } });
  expect((await screen.findByRole("alert")).textContent).toContain(
    "검색 연결 실패",
  );
  expect(screen.queryByText("검색 결과가 없습니다.")).toBeNull();
  client.clear();
});

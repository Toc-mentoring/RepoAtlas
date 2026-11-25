// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { GraphDTO } from "../../api/types";
import { GraphFilters } from "./GraphFilters";
import { DiagramChooser } from "./GraphPage";
import { indexSchema, SpecialDetails } from "./SpecialDiagram";
vi.mock("../../api/client", () => ({
  isMock: true,
  api: {
    getCatalog: vi.fn(async () => ({
      run_id: "run",
      items: [
        { type: "directory", availability: "available", reason: null },
        { type: "erd", availability: "unsupported", reason: "DDL 없음" },
      ],
    })),
    createDiagram: vi.fn(async () => ({ diagram_id: "graph-1" })),
  },
}));
afterEach(() => cleanup());
describe("다이어그램 선택 화면", () => {
  it("지원하지 않는 유형을 비활성화하고 사유를 표시한다", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiagramChooser runId="run" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const unsupported = await screen.findByRole("button", {
      name: /ERD 미지원/,
    });
    expect((unsupported as HTMLButtonElement).disabled).toBe(true);
    expect(unsupported.textContent).toContain("DDL 없음");
    expect(screen.getByRole("button", { name: /폴더 구조/ })).toBeTruthy();
  });
  it("유형 버튼을 클릭하면 별도 생성 버튼 없이 다이어그램을 연다", async () => {
    const { api } = await import("../../api/client");
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiagramChooser runId="run" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /폴더 구조/ }));
    await waitFor(() =>
      expect(api.createDiagram).toHaveBeenCalledWith("run", "directory", {
        max_nodes: 150,
        root_path: ".",
        depth: 2,
      }),
    );
  });
});

it.each(["architecture", "erd"] as const)(
  "%s의 최대 노드를 다시 요청할 수 있다",
  (type) => {
    const apply = vi.fn();
    const graph: GraphDTO = {
      diagram_id: "diagram",
      run_id: "run",
      type,
      availability: "available",
      nodes: [],
      edges: [],
      warnings: [],
      truncated: true,
      has_more: true,
      unresolved_references: 0,
    };
    render(<GraphFilters graph={graph} pending={false} apply={apply} />);
    fireEvent.click(screen.getByText("그래프 범위·필터"));
    fireEvent.change(screen.getByRole("spinbutton", { name: "최대 노드" }), {
      target: { value: "300" },
    });
    fireEvent.click(screen.getByRole("button", { name: "필터 적용" }));
    expect(apply).toHaveBeenCalledWith({ max_nodes: 300 });
  },
);

it("복합 외래 키의 컬럼을 선택하면 같은 제약의 컬럼 쌍을 모두 표시한다", () => {
  const tables = ["orders", "stores"];
  const columns = ["region_id", "store_id", "unrelated_id"];
  const graph: GraphDTO = {
    diagram_id: "graph",
    run_id: "run",
    type: "erd",
    availability: "available",
    nodes: tables.flatMap((table) => [
      { id: table, type: "table", label: table, data: {} },
      ...columns.map((column) => ({
        id: `${table}.${column}`,
        type: "column",
        label: column,
        data: {},
      })),
    ]),
    edges: [
      ...tables.flatMap((table) =>
        columns.map((column) => ({
          id: `contains:${table}.${column}`,
          type: "contains",
          source: table,
          target: `${table}.${column}`,
          data: {},
        })),
      ),
      ...columns.map((column, index) => ({
        id: `foreign_key:${column}`,
        type: "foreign_key",
        source: `orders.${column}`,
        target: `stores.${column}`,
        data: {
          constraint_name: index === 2 ? "fk_unrelated" : "fk_store_region",
          ordinal_position: index + 1,
        },
      })),
    ],
    warnings: [],
    truncated: false,
    has_more: false,
    unresolved_references: 0,
  };
  const schema = indexSchema(graph);
  for (const columnId of ["orders.store_id", "stores.region_id"]) {
    const { unmount } = render(
      <SpecialDetails
        graph={graph}
        node={schema.byId.get(columnId)!}
        schema={schema}
        isMock={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("fk_store_region")).toBeTruthy();
    expect(
      screen
        .getAllByRole("button", { name: /^orders\./ })
        .map((button) => button.textContent),
    ).toEqual(["orders.region_id", "orders.store_id"]);
    expect(screen.queryByText("fk_unrelated")).toBeNull();
    unmount();
  }
});

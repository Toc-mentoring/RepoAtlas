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
import { DiagramChooser } from "./GraphPage";
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

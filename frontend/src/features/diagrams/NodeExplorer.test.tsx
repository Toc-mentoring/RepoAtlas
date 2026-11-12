// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NodeExplorer } from "./NodeExplorer";
import type { GraphDTO } from "../../api/types";
const graph: GraphDTO = {
  diagram_id: "diagram",
  run_id: "run",
  type: "directory",
  availability: "available",
  truncated: false,
  has_more: false,
  warnings: [],
  unresolved_references: 0,
  nodes: [
    { id: "dir:.", type: "directory", label: "project", data: { path: "." } },
    { id: "dir:src", type: "directory", label: "src", data: { path: "src" } },
    {
      id: "dir:src/lib",
      type: "directory",
      label: "lib",
      data: { path: "src/lib" },
    },
    {
      id: "file:1",
      type: "file",
      label: "app.ts",
      data: { path: "src/app.ts" },
    },
    {
      id: "file:2",
      type: "file",
      label: "util.ts",
      data: { path: "src/lib/util.ts" },
    },
  ],
  edges: [],
};
afterEach(cleanup);
describe("파일 탐색기", () => {
  it("폴더를 펼치고 접으며 파일 선택을 전달한다", () => {
    const select = vi.fn();
    render(
      <NodeExplorer
        graph={graph}
        selected={null}
        search=""
        onSearch={vi.fn()}
        onSelect={select}
      />,
    );
    expect(screen.queryByRole("button", { name: "app.ts" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "src 펼치기" }));
    expect(screen.getByRole("button", { name: "app.ts" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "lib 펼치기" }));
    fireEvent.click(screen.getByRole("button", { name: "util.ts" }));
    expect(select).toHaveBeenCalledWith("file:2");
    fireEvent.click(screen.getByRole("button", { name: "src 접기" }));
    expect(screen.queryByRole("button", { name: "util.ts" })).toBeNull();
  });
  it("종류와 검색 결과에서 조상 폴더를 유지한다", () => {
    const { rerender } = render(
      <NodeExplorer
        graph={graph}
        selected={null}
        search=""
        onSearch={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("노드 종류"), {
      target: { value: "file" },
    });
    expect(screen.getByRole("button", { name: "util.ts" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "src" })).toBeTruthy();
    rerender(
      <NodeExplorer
        graph={graph}
        selected={null}
        search="app.ts"
        onSearch={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "app.ts" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "util.ts" })).toBeNull();
  });
});

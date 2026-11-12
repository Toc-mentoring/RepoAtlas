// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Root from "./Root";
import { api } from "./api/client";

beforeEach(() => {
  localStorage.clear();
  history.pushState({}, "", "/repositories");
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("저장소와 커밋 SHA를 입력하면 해당 SHA로 분석을 요청한다", async () => {
  const start = vi.spyOn(api, "startAnalysis");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("GitHub 저장소 URL"), {
    target: { value: "https://github.com/acme/example" },
  });
  fireEvent.change(screen.getByLabelText("커밋 해시"), {
    target: { value: "a".repeat(40) },
  });
  fireEvent.click(screen.getByRole("button", { name: /분석 요청/ }));
  await waitFor(
    () =>
      expect(start).toHaveBeenCalledWith(expect.any(String), "a".repeat(40)),
    { timeout: 3000 },
  );
  await waitFor(() => expect(window.location.pathname).toMatch(/^\/runs\//), {
    timeout: 3000,
  });
});

it("테마 버튼으로 변경한 설정을 저장한다", () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "라이트 모드로 변경" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("repoatlas.theme")).toBe("light");
});

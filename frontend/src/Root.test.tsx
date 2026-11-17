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

it("다음 페이지 오류가 나도 기존 저장소를 유지하고 더 보기로 재시도한다", async () => {
  const first = {
    id: "repo-1",
    owner: "acme",
    name: "first-repo",
    default_branch: "main",
    latest_run_id: null,
  };
  const second = { ...first, id: "repo-2", name: "second-repo" };
  const list = vi
    .spyOn(api, "listRepositories")
    .mockResolvedValueOnce({ items: [first], next_cursor: "opaque-next" })
    .mockRejectedValueOnce(new Error("다음 페이지 연결 실패"))
    .mockResolvedValueOnce({ items: [first, second], next_cursor: null });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>,
  );
  await screen.findByText("first-repo", { selector: "b" });
  fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
  await screen.findByRole("alert");
  expect(screen.getByText("first-repo", { selector: "b" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  await screen.findByText("second-repo", { selector: "b" });
  expect(screen.getAllByText("first-repo", { selector: "b" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "더 보기" })).toBeNull();
  expect(list).toHaveBeenLastCalledWith({ cursor: "opaque-next" });
  client.clear();
});

it("현재 백엔드에서는 SHA 입력을 숨기고 기본 브랜치 HEAD를 요청한다", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["backend-capabilities"], {
    commitSha: false,
    repositoryPagination: false,
    historyPagination: false,
  });
  const start = vi.spyOn(api, "startAnalysis");
  const list = vi.spyOn(api, "listRepositories");
  render(
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>,
  );
  expect(screen.queryByLabelText("커밋 해시")).toBeNull();
  expect(screen.getByText("기본 브랜치의 최신 커밋(HEAD)")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("GitHub 저장소 URL"), {
    target: { value: "https://github.com/acme/head-test" },
  });
  fireEvent.click(screen.getByRole("button", { name: /분석 요청/ }));
  await waitFor(
    () => expect(start).toHaveBeenCalledWith(expect.any(String), undefined),
    { timeout: 3000 },
  );
  expect(list).toHaveBeenCalledWith({ cursor: null, limit: 100 });
  await waitFor(() => expect(window.location.pathname).toMatch(/^\/runs\//), {
    timeout: 3000,
  });
  client.clear();
});

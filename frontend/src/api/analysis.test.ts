// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { mockApi } from "./mock";

beforeEach(() => localStorage.clear());

describe("커밋 지정 분석", () => {
  it("입력한 SHA를 보존하고 같은 SHA만 재사용한다", async () => {
    const repo = await mockApi.createRepository(
      "https://github.com/acme/sha-test",
    );
    const first = await mockApi.startAnalysis(repo.id, "A".repeat(40));
    const same = await mockApi.startAnalysis(repo.id, "a".repeat(40));
    const other = await mockApi.startAnalysis(repo.id, "b".repeat(40));
    expect(first.commit_sha).toBe("a".repeat(40));
    expect(same.run_id).toBe(first.run_id);
    expect(same.reused).toBe(true);
    expect(other.run_id).not.toBe(first.run_id);
    expect(other.commit_sha).toBe("b".repeat(40));
  });

  it("유효하지 않은 SHA를 거부한다", async () => {
    const repo = await mockApi.createRepository(
      "https://github.com/acme/sha-test",
    );
    await expect(mockApi.startAnalysis(repo.id, "abc")).rejects.toMatchObject({
      status: 422,
      error: { code: "INVALID_COMMIT_SHA" },
    });
  });
});

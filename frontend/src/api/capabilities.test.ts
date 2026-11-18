import { expect, it } from "vitest";
import { readCapabilities } from "./capabilities";

import { currentSchema } from "../../tests/fixtures/backendSchema";
it("현재 GitHub 백엔드의 HEAD 분석·미지원 목록 cursor를 판별한다", () => {
  expect(readCapabilities(currentSchema)).toEqual({
    commitSha: false,
    repositoryPagination: false,
    historyPagination: false,
  });
});
it("참조 요청 스키마와 cursor가 추가되면 지정 SHA와 페이지 기능을 활성화한다", () => {
  const next = structuredClone(currentSchema) as any;
  next.components = {
    schemas: {
      AnalysisCreate: {
        type: "object",
        properties: { commit_sha: { type: "string" } },
      },
    },
  };
  next.paths["/api/v1/repositories/{repo_id}/analyses"].post.requestBody = {
    content: {
      "application/json": {
        schema: { $ref: "#/components/schemas/AnalysisCreate" },
      },
    },
  };
  Object.values(next.paths).forEach((p: any) =>
    p.get.parameters.push({ name: "cursor", in: "query" }),
  );
  expect(readCapabilities(next)).toEqual({
    commitSha: true,
    repositoryPagination: true,
    historyPagination: true,
  });
});
it("잘못된 서버 스키마를 HEAD 지원으로 추정하지 않는다", () => {
  expect(() => readCapabilities({ paths: {} })).toThrow("RepoAtlas");
  const bad = structuredClone(currentSchema) as any;
  bad.paths["/api/v1/repositories/{repo_id}/analyses"].post.requestBody = {
    $ref: "#/components/requestBodies/Missing",
  };
  expect(() => readCapabilities(bad)).toThrow();
});

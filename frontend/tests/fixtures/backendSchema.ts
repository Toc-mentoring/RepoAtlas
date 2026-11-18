// Operation excerpt checked against Toc-mentoring/RepoAtlas develop 0260436.
export const currentSchema = {
  openapi: "3.1.0",
  paths: {
    "/api/v1/repositories": {
      get: { parameters: [{ in: "query", name: "limit" }] },
    },
    "/api/v1/repositories/{repo_id}/analyses": {
      get: { parameters: [{ in: "query", name: "limit" }] },
      post: {},
    },
  },
};

export type BackendCapabilities = {
  commitSha: boolean;
  repositoryPagination: boolean;
  historyPagination: boolean;
};

// Read only documented OpenAPI operations. No probe POSTs or guessed feature flags.
export function readCapabilities(
  document: Record<string, any>,
): BackendCapabilities {
  function resolve(value: any, seen = new Set<string>()): any {
    if (!value || typeof value !== "object")
      throw new Error("API 스키마를 읽을 수 없습니다.");
    if (!value.$ref) return value;
    if (
      typeof value.$ref !== "string" ||
      !value.$ref.startsWith("#/") ||
      seen.has(value.$ref)
    )
      throw new Error("지원하지 않는 API 스키마 참조입니다.");
    seen.add(value.$ref);
    const target = value.$ref
      .slice(2)
      .split("/")
      .reduce(
        (item: any, key: string) =>
          item?.[key.replace(/~1/g, "/").replace(/~0/g, "~")],
        document,
      );
    return resolve(target, seen);
  }
  const entries = Object.entries(document.paths || {}) as [string, any][];
  const repository = entries.find(([path]) =>
    /\/repositories$/.test(path),
  )?.[1];
  const analyses = entries.find(([path]) =>
    /\/repositories\/\{[^/]+\}\/analyses$/.test(path),
  )?.[1];
  if (!repository?.get || !analyses?.get || !analyses?.post)
    throw new Error("RepoAtlas 저장소·분석 API를 스키마에서 찾지 못했습니다.");
  function property(schema: any, depth = 0): boolean {
    if (depth > 12) throw new Error("API 요청 스키마 참조가 너무 깊습니다.");
    const item = resolve(schema);
    return (
      !!item.properties?.commit_sha ||
      ["allOf", "anyOf", "oneOf"].some(
        (key) =>
          Array.isArray(item[key]) &&
          item[key].some((part: any) => property(part, depth + 1)),
      )
    );
  }
  const body = analyses.post.requestBody
    ? resolve(analyses.post.requestBody)
    : undefined;
  const cursor = (path: any, op: any) =>
    [...(path.parameters || []), ...(op.parameters || [])].some((p) => {
      const item = resolve(p);
      return item.in === "query" && item.name === "cursor";
    });
  return {
    commitSha: body
      ? property(body.content?.["application/json"]?.schema)
      : false,
    repositoryPagination: cursor(repository, repository.get),
    historyPagination: cursor(analyses, analyses.get),
  };
}

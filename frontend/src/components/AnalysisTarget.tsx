import { useQuery } from "@tanstack/react-query";
import { api, isMock } from "../api/client";
import { Feedback } from "./Feedback";

export function useBackendCapabilities() {
  return useQuery({
    queryKey: ["backend-capabilities"],
    queryFn: api.getCapabilities,
    retry: false,
    staleTime: Infinity,
    initialData: isMock
      ? { commitSha: true, repositoryPagination: true, historyPagination: true }
      : undefined,
  });
}

export function AnalysisTarget({
  capabilities,
  sha,
  onChange,
}: {
  capabilities: ReturnType<typeof useBackendCapabilities>;
  sha: string;
  onChange: (value: string) => void;
}) {
  if (capabilities.isError)
    return (
      <Feedback
        error={capabilities.error}
        retry={() => capabilities.refetch()}
      />
    );
  if (!capabilities.data)
    return <p role="status">서버의 분석 요청 방식을 확인하는 중입니다…</p>;
  if (!capabilities.data.commitSha)
    return (
      <div className="field analysis-target">
        <span>분석 대상</span>
        <p>기본 브랜치의 최신 커밋(HEAD)</p>
        <small>
          현재 서버는 지정 SHA 분석을 지원하지 않습니다. 실제 분석 SHA는 요청 후
          표시합니다.
        </small>
      </div>
    );
  return (
    <label className="field">
      <span>커밋 해시</span>
      <div className="input-wrap">
        <input
          aria-label="커밋 해시"
          value={sha}
          onChange={(e) => onChange(e.target.value)}
          placeholder="40자리 커밋 SHA"
          pattern="[a-fA-F0-9]{40}"
          minLength={40}
          maxLength={40}
          required
          spellCheck={false}
        />
      </div>
    </label>
  );
}

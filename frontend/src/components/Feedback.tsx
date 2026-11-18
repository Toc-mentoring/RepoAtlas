import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, errorMessage } from "../api/errors";

export function Feedback({
  error,
  retry,
  runId,
}: {
  error: unknown;
  retry?: () => void;
  runId?: string;
}) {
  const [, tick] = useState(0);
  const until = error instanceof ApiError ? error.retryAt : undefined;
  useEffect(() => {
    if (!until) return;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [until]);
  const wait = until ? Math.max(0, Math.ceil((until - Date.now()) / 1000)) : 0;
  const notReady =
    error instanceof ApiError && error.error.code === "ANALYSIS_NOT_READY";
  return (
    <div className="notice fail" role="alert">
      <span>{errorMessage(error)}</span>
      {notReady && runId && <Link to={`/runs/${runId}`}>분석 상태 확인</Link>}
      {retry && (
        <button className="back" disabled={wait > 0} onClick={retry}>
          {wait ? `${wait}초 후 재시도` : "다시 시도"}
        </button>
      )}
    </div>
  );
}

export function MoreButton({
  more,
  pending,
  load,
}: {
  more: boolean;
  pending: boolean;
  load: () => void;
}) {
  return more ? (
    <button className="outline load-more" disabled={pending} onClick={load}>
      {pending ? "불러오는 중…" : "더 보기"}
    </button>
  ) : null;
}

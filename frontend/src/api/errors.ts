export class ApiError extends Error {
  constructor(
    public status: number,
    public error: {
      code: string;
      message: string;
      details: Record<string, unknown>;
      request_id: string;
    },
    public retryAt?: number,
  ) {
    super(error.message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError))
    return error instanceof Error
      ? error.message
      : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";
  const detail = error.error;
  const wait = error.retryAt
    ? Math.max(0, Math.ceil((error.retryAt - Date.now()) / 1000))
    : 0;
  return [
    detail.message,
    wait ? `${wait}초 후 다시 시도해 주세요.` : "",
    detail.request_id ? `문의 ID: ${detail.request_id}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * Typed HTTP client for the HexTrack API (`/api/v1`), generated from openapi.json.
 *
 * `api` is the raw openapi-fetch client; `request()` unwraps a call and throws `ApiError`
 * so TanStack Query sees failures. Never call `fetch` directly from components.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** Machine-readable error codes the backend sends in `{"detail", "code"}` bodies. */
export type ApiErrorCode =
  | "riot_key"
  | "riot_rate_limited"
  | "riot_unavailable"
  | "not_found"
  | "model_missing"
  | "unauthorized"
  | "forbidden"
  | "invalid_riot_id"
  | "validation_error"
  | "network"
  | (string & {});

export class ApiError extends Error {
  /** HTTP status; 0 for network failures (API unreachable). */
  readonly status: number;
  /** Human-readable reason from the server (safe to show). */
  readonly detail: string;
  /** Machine-readable reason, when the server sent one. */
  readonly code: ApiErrorCode | null;
  /** Seconds from a `Retry-After` header (429s), when present. */
  readonly retryAfter: number | null;

  constructor(status: number, detail: string, code: ApiErrorCode | null = null, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.retryAfter = retryAfter;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }

  get isRiotKeyMissing(): boolean {
    return this.code === "riot_key";
  }

  get isModelMissing(): boolean {
    return this.status === 503 && this.code === "model_missing";
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export const api = createClient<paths>({ baseUrl: "" });

interface ValidationIssue {
  msg?: unknown;
  loc?: unknown;
}

function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = (detail as ValidationIssue[])
      .map((issue) => (typeof issue.msg === "string" ? issue.msg : null))
      .filter((msg): msg is string => msg !== null);
    if (messages.length > 0) return messages.join("; ");
  }
  return fallback;
}

const UNREACHABLE_MESSAGE = "Can't reach the HexTrack API. Check that the server is running.";
const GATEWAY_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);

/** Build an ApiError from an openapi-fetch error body + response. */
export function toApiError(body: unknown, response: Response): ApiError {
  const fallback = response.statusText || `Request failed (${response.status})`;
  let detail = fallback;
  let code: string | null = null;
  if (body && typeof body === "object") {
    const record = body as { detail?: unknown; code?: unknown };
    detail = describeDetail(record.detail, fallback);
    if (typeof record.code === "string") code = record.code;
    else if (response.status === 422) code = "validation_error";
  } else if (typeof body === "string" && body.trim()) {
    detail = body;
  }
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter = retryHeader !== null && Number.isFinite(Number(retryHeader)) ? Number(retryHeader) : null;
  // The API always answers errors with a `code`; a 502/503/504 without one comes from a proxy in
  // front of it (e.g. the Vite dev proxy while the API is down), so it is a reachability problem.
  if (code === null && GATEWAY_STATUSES.has(response.status)) {
    return new ApiError(response.status, UNREACHABLE_MESSAGE, "network", retryAfter);
  }
  return new ApiError(response.status, detail, code, retryAfter);
}

interface FetchResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

/** The success payload type of an openapi-fetch result. */
export type ResultData<R extends FetchResult> = Exclude<R["data"], undefined>;

/**
 * Await an openapi-fetch call and return its data, or throw an ApiError.
 *
 * ```ts
 * const health = await request(api.GET("/api/v1/health", { signal }));
 * ```
 */
export async function request<R extends FetchResult>(call: Promise<R>): Promise<ResultData<R>> {
  let result: R;
  try {
    result = await call;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, UNREACHABLE_MESSAGE, "network");
  }
  if (result.error !== undefined || !result.response.ok) {
    throw toApiError(result.error, result.response);
  }
  return result.data as ResultData<R>;
}

/** Friendly one-line message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.detail;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

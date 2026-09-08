import type { ErrorEnvelope, ResultEnvelope, UploadResponse } from './types';

const HEALTH_TIMEOUT_MS = 15_000;
const QUERY_TIMEOUT_MS = 30_000;
const UPLOAD_TIMEOUT_MS = 120_000;

export class SatQueryApiError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly status: number | null;

  constructor(
    message: string,
    options: {
      code?: string;
      details?: Record<string, unknown>;
      status?: number | null;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = 'SatQueryApiError';
    this.code = options.code ?? 'request_failed';
    this.details = options.details ?? {};
    this.status = options.status ?? null;
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetchWithTimeout('/api/health', { method: 'GET' }, HEALTH_TIMEOUT_MS);
    if (!response.ok) {
      return false;
    }
    const payload: unknown = await response.json();
    return isRecord(payload) && payload.status === 'ok';
  } catch {
    return false;
  }
}

export async function uploadScene(
  file: File,
  modality: 'auto' | 'optical' | 'sar',
  date?: string,
): Promise<UploadResponse> {
  const body = new FormData();
  body.append('file', file);
  body.append('modality', modality);
  const acquisitionDate = date?.trim();
  if (acquisitionDate) {
    body.append('acquisition_date', acquisitionDate);
  }

  const response = await fetchWithTimeout(
    '/api/upload',
    { method: 'POST', body },
    UPLOAD_TIMEOUT_MS,
  );
  if (!response.ok) {
    throw await readApiError(response);
  }
  return readJson<UploadResponse>(response);
}

export async function queryScenes(
  assetIds: string[],
  question: string,
): Promise<ResultEnvelope> {
  const response = await fetchWithTimeout(
    '/api/query',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_ids: assetIds, question }),
    },
    QUERY_TIMEOUT_MS,
  );
  if (!response.ok) {
    throw await readApiError(response);
  }
  return readJson<ResultEnvelope>(response);
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    throw toFriendlyError(error, timeoutMs);
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

function toFriendlyError(error: unknown, timeoutMs: number): SatQueryApiError {
  if (error instanceof SatQueryApiError) {
    return error;
  }
  if (isAbortError(error)) {
    const seconds = Math.round(timeoutMs / 1000);
    return new SatQueryApiError(
      `The SatQuery API did not respond within ${seconds} seconds. Confirm the local SatQuery server is running.`,
      { code: 'timeout' },
    );
  }
  return new SatQueryApiError(
    'Cannot reach the SatQuery API. Start the local SatQuery server, then try again.',
    { code: 'network_error' },
  );
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  );
}

async function readApiError(response: Response): Promise<SatQueryApiError> {
  try {
    const payload: unknown = await response.json();
    if (isErrorEnvelope(payload)) {
      return new SatQueryApiError(payload.error.message, {
        code: payload.error.code,
        details: payload.error.details ?? {},
        status: response.status,
      });
    }
  } catch {
    // Fall through to a generic HTTP message when the body is not an error envelope.
  }
  return new SatQueryApiError(
    `The SatQuery API returned an unexpected response (HTTP ${response.status}).`,
    { code: 'unexpected_response', status: response.status },
  );
}

async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new SatQueryApiError('The SatQuery API returned a response that was not JSON.', {
      code: 'invalid_json',
      status: response.status,
      cause: error,
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false;
  }
  return typeof value.error.code === 'string' && typeof value.error.message === 'string';
}

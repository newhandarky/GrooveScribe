import type {
  JobStatusResponse,
  LocalDataSummaryResponse,
  RuntimePreflightResponse,
  TranscriptionJobListResponse,
  TranscriptionResultResponse,
  UploadAcceptedResponse,
} from './types';

const API_PREFIX = '/api/v1';

interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    retriable?: boolean;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(
    message: string,
    options: { code: string; status: number; details?: Record<string, unknown> },
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status;
    this.details = options.details ?? {};
  }
}

export async function getRuntimePreflight(fetcher: typeof fetch = fetch): Promise<RuntimePreflightResponse> {
  return requestJson<RuntimePreflightResponse>('/runtime/preflight', { fetcher });
}

export async function getLocalDataSummary(fetcher: typeof fetch = fetch): Promise<LocalDataSummaryResponse> {
  return requestJson<LocalDataSummaryResponse>('/local-data/summary', { fetcher });
}

export async function listTranscriptions(
  limit = 20,
  fetcher: typeof fetch = fetch,
): Promise<TranscriptionJobListResponse> {
  return requestJson<TranscriptionJobListResponse>(`/transcriptions?limit=${encodeURIComponent(limit)}`, { fetcher });
}

export async function uploadTranscription(
  input: { file: File; title?: string },
  fetcher: typeof fetch = fetch,
): Promise<UploadAcceptedResponse> {
  const formData = new FormData();
  formData.set('file', input.file);
  if (input.title?.trim()) {
    formData.set('title', input.title.trim());
  }
  return requestJson<UploadAcceptedResponse>('/transcriptions', {
    fetcher,
    init: {
      method: 'POST',
      body: formData,
    },
  });
}

export async function getTranscriptionStatus(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`/transcriptions/${encodeURIComponent(jobId)}/status`, { fetcher });
}

export async function getTranscriptionResult(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<TranscriptionResultResponse> {
  return requestJson<TranscriptionResultResponse>(`/transcriptions/${encodeURIComponent(jobId)}`, { fetcher });
}

export async function retryTranscription(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<UploadAcceptedResponse> {
  return requestJson<UploadAcceptedResponse>(`/transcriptions/${encodeURIComponent(jobId)}/retry`, {
    fetcher,
    init: { method: 'POST' },
  });
}

export function downloadUrl(url: string | null): string {
  return url ?? '#';
}

async function requestJson<T>(
  path: string,
  options: { fetcher: typeof fetch; init?: RequestInit },
): Promise<T> {
  const response = await options.fetcher.call(globalThis, `${API_PREFIX}${path}`, {
    ...options.init,
    headers: {
      Accept: 'application/json',
      ...options.init?.headers,
    },
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as T | ApiErrorPayload) : {};
  if (!response.ok) {
    const apiError = (payload as ApiErrorPayload).error;
    throw new ApiError(apiError?.message ?? 'API request failed.', {
      code: apiError?.code ?? 'API_ERROR',
      status: response.status,
      details: apiError?.details ?? {},
    });
  }
  return payload as T;
}

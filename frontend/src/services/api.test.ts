import { describe, expect, it } from 'vitest';

import {
  ApiError,
  downloadUrl,
  getRuntimePreflight,
  getTranscriptionResult,
  getTranscriptionStatus,
  uploadTranscription,
} from './api';

function jsonResponse(payload: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

describe('api client', () => {
  it('loads runtime preflight from the v1 API', async () => {
    const calls: string[] = [];
    const fetcher = async (url: string | URL | Request) => {
      calls.push(String(url));
      return jsonResponse({
        status: 'degraded',
        mock_ai_ready: true,
        true_ai_ready: false,
        missing_requirements: ['ADTOF not configured'],
        checks: {},
        smoke_commands: {},
        checked_at: '2026-07-02T00:00:00Z',
        error: null,
      });
    };

    const response = await getRuntimePreflight(fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/runtime/preflight']);
    expect(response.status).toBe('degraded');
    expect(response.mock_ai_ready).toBe(true);
  });

  it('loads job status with encoded id', async () => {
    const calls: string[] = [];
    const fetcher = async (url: string | URL | Request) => {
      calls.push(String(url));
      return jsonResponse({
        job_id: 'job 1',
        status: 'processing',
        stage: 'source_separation',
        progress: 25,
        message: 'Running',
        error: null,
        created_at: '2026-07-02T00:00:00Z',
      });
    };

    const response = await getTranscriptionStatus('job 1', fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/transcriptions/job%201/status']);
    expect(response.progress).toBe(25);
  });

  it('uploads an audio file as form data', async () => {
    const calls: Array<{ url: string; method?: string; bodyIsFormData: boolean }> = [];
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method,
        bodyIsFormData: init?.body instanceof FormData,
      });
      return jsonResponse({
        job_id: 'job-1',
        status: 'queued',
        status_url: '/api/v1/transcriptions/job-1/status',
        result_url: '/api/v1/transcriptions/job-1',
        created_at: '2026-07-02T00:00:00Z',
      });
    };

    const response = await uploadTranscription(
      { file: new File(['audio'], 'demo.wav', { type: 'audio/wav' }), title: 'Demo' },
      fetcher as typeof fetch,
    );

    expect(calls).toEqual([{ url: '/api/v1/transcriptions', method: 'POST', bodyIsFormData: true }]);
    expect(response.job_id).toBe('job-1');
  });

  it('loads completed result exports', async () => {
    const fetcher = async () =>
      jsonResponse({
        job_id: 'job-1',
        status: 'completed',
        stage: 'completed',
        title: 'Demo',
        created_at: '2026-07-02T00:00:00Z',
        completed_at: '2026-07-02T00:01:00Z',
        audio: {
          id: 'audio-1',
          file_name: 'demo.wav',
          content_type: 'audio/wav',
          file_size_bytes: 128,
          duration_seconds: 2,
          sample_rate: 44100,
          channels: 2,
        },
        drum_track: null,
        preview: { musicxml_url: '/api/v1/transcriptions/job-1/download/musicxml' },
        exports: [
          {
            type: 'musicxml',
            status: 'available',
            content_type: 'application/vnd.recordare.musicxml+xml',
            file_size_bytes: 42,
            checksum: 'abc',
            download_url: '/api/v1/transcriptions/job-1/download/musicxml',
          },
        ],
      });

    const result = await getTranscriptionResult('job-1', fetcher as typeof fetch);

    expect(result.exports[0].download_url).toBe('/api/v1/transcriptions/job-1/download/musicxml');
    expect(downloadUrl(result.exports[0].download_url)).toBe('/api/v1/transcriptions/job-1/download/musicxml');
    expect(downloadUrl(null)).toBe('#');
  });

  it('maps unified API errors', async () => {
    const fetcher = async () =>
      jsonResponse(
        {
          error: {
            code: 'JOB_NOT_FOUND',
            message: '找不到指定的分析任務。',
            retriable: false,
            details: { job_id: 'missing' },
          },
        },
        { status: 404 },
      );

    await expect(getTranscriptionStatus('missing', fetcher as typeof fetch)).rejects.toMatchObject({
      code: 'JOB_NOT_FOUND',
      status: 404,
      message: '找不到指定的分析任務。',
    } satisfies Partial<ApiError>);
  });
});

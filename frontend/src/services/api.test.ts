import { describe, expect, it } from 'vitest';

import {
  ApiError,
  downloadUrl,
  getLocalDataSummary,
  getReviewPacket,
  getRuntimePreflight,
  getTranscriptionResult,
  getTranscriptionStatus,
  listTranscriptions,
  retryTranscription,
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
        generic_baseline_ready: false,
        demo_mock_ready: true,
        missing_requirements: ['Demucs not configured'],
        checks: {},
        offline_evaluation: {},
        smoke_commands: {},
        checked_at: '2026-07-02T00:00:00Z',
        error: null,
      });
    };

    const response = await getRuntimePreflight(fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/runtime/preflight']);
    expect(response.status).toBe('degraded');
    expect(response.demo_mock_ready).toBe(true);
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
    const calls: Array<{ url: string; method?: string; bodyIsFormData: boolean; entries: Record<string, string> }> = [];
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      const formData = init?.body instanceof FormData ? init.body : null;
      calls.push({
        url: String(url),
        method: init?.method,
        bodyIsFormData: Boolean(formData),
        entries: formData ? formDataEntries(formData) : {},
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
      {
        file: new File(['audio'], 'demo.wav', { type: 'audio/wav' }),
        title: 'Demo',
        pipelineMode: 'generic_baseline',
      },
      fetcher as typeof fetch,
    );

    expect(calls).toEqual([
      {
        url: '/api/v1/transcriptions',
        method: 'POST',
        bodyIsFormData: true,
        entries: {
          pipeline_mode: 'generic_baseline',
          title: 'Demo',
        },
      },
    ]);
    expect(response.job_id).toBe('job-1');
  });

  it('loads recent transcriptions with a bounded limit', async () => {
    const calls: string[] = [];
    const fetcher = async (url: string | URL | Request) => {
      calls.push(String(url));
      return jsonResponse({
        jobs: [
          {
            job_id: 'job-1',
            title: 'Demo',
            file_name: 'demo.wav',
            status: 'completed',
            stage: 'completed',
            progress: 100,
            created_at: '2026-07-02T00:00:00Z',
            completed_at: '2026-07-02T00:01:00Z',
            failed_at: null,
            exports: { midi: 'available' },
            error: null,
          },
        ],
        limit: 5,
      });
    };

    const response = await listTranscriptions(5, fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/transcriptions?limit=5']);
    expect(response.jobs[0].job_id).toBe('job-1');
    expect(response.jobs[0].exports.midi).toBe('available');
  });

  it('retries a transcription with encoded id', async () => {
    const calls: Array<{ url: string; method?: string }> = [];
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method });
      return jsonResponse({
        job_id: 'retry-job',
        status: 'queued',
        status_url: '/api/v1/transcriptions/retry-job/status',
        result_url: '/api/v1/transcriptions/retry-job',
        created_at: '2026-07-02T00:00:00Z',
      });
    };

    const response = await retryTranscription('job 1', fetcher as typeof fetch);

    expect(calls).toEqual([{ url: '/api/v1/transcriptions/job%201/retry', method: 'POST' }]);
    expect(response.job_id).toBe('retry-job');
  });

  it('retries a transcription with the generic baseline config', async () => {
    const calls: Array<{ url: string; method?: string; entries: Record<string, string> }> = [];
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method,
        entries: init?.body instanceof FormData ? formDataEntries(init.body) : {},
      });
      return jsonResponse({
        job_id: 'retry-job',
        status: 'queued',
        status_url: '/api/v1/transcriptions/retry-job/status',
        result_url: '/api/v1/transcriptions/retry-job',
        created_at: '2026-07-02T00:00:00Z',
      });
    };

    await retryTranscription(
      'job 1',
      {
        pipelineMode: 'generic_baseline',
      },
      fetcher as typeof fetch,
    );

    expect(calls).toEqual([
      {
        url: '/api/v1/transcriptions/job%201/retry',
        method: 'POST',
        entries: {
          pipeline_mode: 'generic_baseline',
        },
      },
    ]);
  });

  it('loads local data summary from a public-safe endpoint', async () => {
    const calls: string[] = [];
    const fetcher = async (url: string | URL | Request) => {
      calls.push(String(url));
      return jsonResponse({
        schema_version: '1.0',
        status: 'dry_run',
        dry_run: true,
        execute_supported: false,
        storage_root_name: 'storage',
        job_dir_count: 2,
        database_status: 'readable',
        database_job_count: 1,
        orphan_job_dir_count: 1,
        warnings: [],
      });
    };

    const response = await getLocalDataSummary(fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/local-data/summary']);
    expect(response.execute_supported).toBe(false);
    expect(response.storage_root_name).toBe('storage');
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
        pipeline: {
          mode: 'mock',
          status: 'completed',
          stages: [],
          artifacts: [],
          warnings: ['mock_ai_enabled'],
          pipeline_log_available: true,
        },
      });

    const result = await getTranscriptionResult('job-1', fetcher as typeof fetch);

    expect(result.exports[0].download_url).toBe('/api/v1/transcriptions/job-1/download/musicxml');
    expect(result.pipeline?.mode).toBe('mock');
    expect(downloadUrl(result.exports[0].download_url)).toBe('/api/v1/transcriptions/job-1/download/musicxml');
    expect(downloadUrl(null)).toBe('#');
  });

  it('loads review packet with encoded id', async () => {
    const calls: string[] = [];
    const fetcher = async (url: string | URL | Request) => {
      calls.push(String(url));
      return jsonResponse({
        schema_version: '1.0',
        status: 'ready',
        job: { job_id: 'job 1' },
        audio: { file_name: 'demo.wav' },
        exports: [],
        quality: null,
        validation: null,
        review_checklist: [],
        manual_eval_seed: { artifact_ref: 'review:job 1' },
        redaction: { status: 'passed', unsafe_token_count: 0 },
      });
    };

    const packet = await getReviewPacket('job 1', fetcher as typeof fetch);

    expect(calls).toEqual(['/api/v1/transcriptions/job%201/review-packet']);
    expect(packet.schema_version).toBe('1.0');
    expect(packet.status).toBe('ready');
    expect(packet.manual_eval_seed.artifact_ref).toBe('review:job 1');
    expect(packet.redaction).toEqual({ status: 'passed', unsafe_token_count: 0 });
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

function formDataEntries(formData: FormData): Record<string, string> {
  const entries: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (typeof value === 'string') {
      entries[key] = value;
    }
  }
  return entries;
}

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { JobStatusCard, ResultCard, RuntimePanel } from './App';
import type {
  JobStatusResponse,
  RuntimePreflightResponse,
  TranscriptionResultResponse,
} from './services/types';

function runtimeFixture(overrides: Partial<RuntimePreflightResponse> = {}): RuntimePreflightResponse {
  return {
    status: 'degraded',
    mock_ai_ready: true,
    true_ai_ready: false,
    missing_requirements: ['ADTOF runtime is not verified'],
    checks: {
      ai_python: { available: true },
      ffmpeg: { ready: true },
      demucs: { ready: true },
      adtof: { ready: false },
      musescore_pdf: { ready: false },
    },
    smoke_commands: {
      runtime_check: 'PYTHONPATH=. /Users/dev/private/.venv-ai/bin/python scripts/check_ai_runtime.py',
    },
    checked_at: '2026-07-02T00:00:00Z',
    error: null,
    ...overrides,
  };
}

function resultFixture(overrides: Partial<TranscriptionResultResponse> = {}): TranscriptionResultResponse {
  return {
    job_id: 'job-1',
    status: 'completed',
    stage: 'completed',
    title: 'Demo Groove',
    created_at: '2026-07-02T00:00:00Z',
    completed_at: '2026-07-02T00:01:00Z',
    audio: {
      id: 'audio-1',
      file_name: 'demo.wav',
      content_type: 'audio/wav',
      file_size_bytes: 2048,
      duration_seconds: 12,
      sample_rate: 44100,
      channels: 2,
    },
    drum_track: {
      id: 'track-1',
      estimated_bpm: 120,
      time_signature: '4/4',
      event_count: 5,
      confidence_label: 'medium',
      warnings: ['pdf_export_failed'],
    },
    preview: { musicxml_url: '/api/v1/transcriptions/job-1/download/musicxml' },
    exports: [
      {
        type: 'midi',
        status: 'available',
        content_type: 'audio/midi',
        file_size_bytes: 128,
        checksum: 'midi-checksum',
        download_url: '/api/v1/transcriptions/job-1/download/midi',
      },
      {
        type: 'musicxml',
        status: 'available',
        content_type: 'application/vnd.recordare.musicxml+xml',
        file_size_bytes: 256,
        checksum: 'musicxml-checksum',
        download_url: '/api/v1/transcriptions/job-1/download/musicxml',
      },
      {
        type: 'pdf',
        status: 'failed',
        content_type: 'application/pdf',
        file_size_bytes: null,
        checksum: null,
        download_url: null,
      },
    ],
    ...overrides,
  };
}

describe('local app smoke rendering', () => {
  it.each(['ready', 'degraded', 'not_ready', 'error'] as const)('renders runtime status %s safely', (status) => {
    const html = renderToStaticMarkup(
      <RuntimePanel
        runtime={runtimeFixture({
          status,
          mock_ai_ready: status !== 'not_ready' && status !== 'error',
          true_ai_ready: status === 'ready',
          error: status === 'error' ? { code: 'RUNTIME_PREFLIGHT_FAILED', message: 'Runtime preflight command failed.' } : null,
        })}
        loading={false}
        error={null}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain('本機 AI 環境');
    expect(html).toContain(status === 'ready' ? 'True AI' : 'Mock pipeline');
    expect(html).not.toContain('/Users/dev/private');
    expect(html).not.toContain('check_ai_runtime.py');
  });

  it('renders completed result downloads while leaving optional PDF unavailable', () => {
    const html = renderToStaticMarkup(<ResultCard result={resultFixture()} />);

    expect(html).toContain('Demo Groove');
    expect(html).toContain('5 events');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/midi');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/musicxml');
    expect(html).toContain('PDF');
    expect(html).toContain('failed');
    expect(html).not.toContain('href="#"');
  });

  it('renders interrupted job status as terminal state feedback', () => {
    const status: JobStatusResponse = {
      job_id: 'job-interrupted',
      status: 'interrupted',
      stage: 'failed',
      progress: 45,
      message: '分析中斷，請重新執行任務。',
      error: {
        code: 'PIPELINE_FAILED',
        message: '分析流程中斷，請重新上傳或重新執行任務。',
        stage: 'drum_transcription',
        retriable: true,
      },
      created_at: '2026-07-02T00:00:00Z',
    };

    const html = renderToStaticMarkup(<JobStatusCard status={status} />);

    expect(html).toContain('interrupted');
    expect(html).toContain('分析流程中斷');
    expect(html).toContain('Progress 45%');
  });
});

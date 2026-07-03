import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { JobStatusCard, ResultCard, RuntimePanel, UploadPanel } from './App';
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
      adtof: {
        ready: false,
        status_code: 'verify_input_missing',
        summary: '尚未提供 ADTOF verification input drums stem。',
        next_steps: [
          '先執行 normalize 與 Demucs separation，產生 drums.wav。',
          '設定 GROOVESCRIBE_ADTOF_VERIFY_INPUT 指向該 drums.wav。',
        ],
        optional_env: ['GROOVESCRIBE_ADTOF_CHECKPOINT', 'GROOVESCRIBE_ADTOF_VERIFY_INPUT'],
        output_verification_reason: 'GROOVESCRIBE_ADTOF_VERIFY_INPUT is not set',
      },
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
    pipeline: {
      mode: 'mock',
      status: 'completed',
      stages: [
        {
          name: 'midi_post_processing',
          status: 'completed',
          runtime_seconds: 0.12,
          warnings: ['too_few_events'],
        },
      ],
      artifacts: [
        { type: 'midi', available: true, file_size_bytes: 128, status: 'available' },
        { type: 'musicxml', available: true, file_size_bytes: 256, status: 'available' },
        { type: 'pdf', available: false, file_size_bytes: null, status: 'failed' },
      ],
      warnings: ['mock_ai_enabled', 'too_few_events'],
      quality: {
        raw_event_count: 7,
        processed_event_count: 5,
        raw_note_histogram: { '35': 2, '38': 1, '42': 4 },
        processed_drum_counts: { closed_hat: 2, kick: 2, snare: 1 },
        duration_seconds: 12,
        tempo_bpm: 120,
        estimated_measure_count: 4,
        quality_flags: ['sparse_transcription'],
        warnings: ['sparse_transcription'],
      },
      validation: {
        musicxml: {
          available: true,
          parseable: true,
          error_code: null,
          warnings: [],
        },
        pdf: {
          available: false,
          optional: true,
          openable: null,
          error_code: 'pdf_unavailable',
          warnings: ['pdf_optional_unavailable'],
        },
      },
      pipeline_log_available: true,
    },
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
    expect(html).toContain('ADTOF diagnosis');
    expect(html).toContain('verify_input_missing');
    expect(html).not.toContain('/Users/dev/private');
    expect(html).not.toContain('check_ai_runtime.py');
  });

  it('explains degraded runtime and ADTOF repair steps without raw local paths', () => {
    const html = renderToStaticMarkup(
      <RuntimePanel runtime={runtimeFixture()} loading={false} error={null} onRefresh={() => undefined} />,
    );

    expect(html).toContain('Mock pipeline 可用');
    expect(html).toContain('true AI runtime 尚未 ready');
    expect(html).toContain('先執行 normalize 與 Demucs separation');
    expect(html).toContain('GROOVESCRIBE_ADTOF_VERIFY_INPUT');
    expect(html).not.toContain('/tmp/');
    expect(html).not.toContain('Traceback');
  });

  it('keeps upload available for degraded mock-ready runtime', () => {
    const html = renderToStaticMarkup(
      <UploadPanel
        canUpload
        uploading={false}
        selectedFile={{ name: 'demo.wav' } as File}
        title=""
        runtime={runtimeFixture()}
        onFileChange={() => undefined}
        onTitleChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(html).toContain('開始本機分析');
    expect(html).not.toContain('disabled=""');
  });

  it('keeps upload disabled when runtime is not ready', () => {
    const html = renderToStaticMarkup(
      <UploadPanel
        canUpload={false}
        uploading={false}
        selectedFile={{ name: 'demo.wav' } as File}
        title=""
        runtime={runtimeFixture({ status: 'not_ready', mock_ai_ready: false })}
        onFileChange={() => undefined}
        onTitleChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(html).toContain('Mock pipeline 尚未 ready');
    expect(html).toContain('disabled=""');
  });

  it('renders completed result downloads while leaving optional PDF unavailable', () => {
    const html = renderToStaticMarkup(<ResultCard result={resultFixture()} />);

    expect(html).toContain('Demo Groove');
    expect(html).toContain('MOCK');
    expect(html).toContain('Pipeline summary');
    expect(html).toContain('Raw events');
    expect(html).toContain('Processed events');
    expect(html).toContain('closed_hat: 2');
    expect(html).toContain('sparse_transcription');
    expect(html).toContain('MusicXML preview');
    expect(html).toContain('MusicXML validation');
    expect(html).toContain('parseable');
    expect(html).toContain('PDF validation');
    expect(html).toContain('optional unavailable');
    expect(html).toContain('pdf_optional_unavailable');
    expect(html).toContain('Midi Post Processing');
    expect(html).toContain('mock_ai_enabled');
    expect(html).toContain('5 events');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/midi');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/musicxml');
    expect(html).toContain('PDF');
    expect(html).toContain('failed');
    expect(html).not.toContain('href="#"');
  });

  it('renders true AI pipeline summary without local paths or traceback', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          drum_track: {
            id: 'track-1',
            estimated_bpm: 118,
            time_signature: '4/4',
            event_count: 48,
            confidence_label: null,
            warnings: [],
          },
          pipeline: {
            mode: 'true_ai',
            status: 'completed',
            stages: [
              {
                name: 'drum_transcription',
                status: 'completed',
                runtime_seconds: 8.5,
                warnings: [],
              },
            ],
            artifacts: [],
            warnings: ['hihat_missing_likely'],
            quality: {
              raw_event_count: 7,
              processed_event_count: 7,
              raw_note_histogram: { '35': 1, '47': 6 },
              processed_drum_counts: { kick: 1, tom: 6 },
              duration_seconds: 30,
              tempo_bpm: 118,
              estimated_measure_count: 8,
              quality_flags: ['hihat_missing_likely', 'mostly_tom_output'],
              warnings: ['hihat_missing_likely', 'mostly_tom_output'],
            },
            validation: {
              musicxml: {
                available: true,
                parseable: false,
                error_code: 'musicxml_measure_missing',
                warnings: ['musicxml_measure_missing'],
              },
              pdf: {
                available: true,
                optional: true,
                openable: true,
                error_code: null,
                warnings: [],
              },
            },
            pipeline_log_available: true,
          },
        })}
      />,
    );

    expect(html).toContain('TRUE AI');
    expect(html).toContain('Drum Transcription');
    expect(html).toContain('hihat_missing_likely');
    expect(html).toContain('tom: 6');
    expect(html).not.toContain('/Users/');
    expect(html).not.toContain('/tmp/');
    expect(html).not.toContain('Traceback');
    expect(html).not.toContain('stdout');
    expect(html).not.toContain('stderr');
  });

  it('renders missing validation as not reported for backward-compatible results', () => {
    const html = renderToStaticMarkup(<ResultCard result={resultFixture({ pipeline: null })} />);

    expect(html).toContain('MusicXML preview');
    expect(html).toContain('MusicXML validation');
    expect(html).toContain('PDF validation');
    expect(html).toContain('not reported');
    expect(html).not.toContain('pipeline.validation');
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
    expect(html).toContain('本機服務曾在分析中停止');
    expect(html).toContain('Progress 45%');
  });
});

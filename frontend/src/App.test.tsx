import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  App,
  cleanupFailedChartStart,
  elapsedPlaybackSeconds,
  playbackElapsedSeconds,
  formatEffectiveBpm,
  nearestPlaybackRate,
  practiceBaseBpm,
  practiceModes,
  drumPreviewIntensity,
  JobHistoryPanel,
  isCurrentPlaybackSession,
  JobStatusCard,
  LocalDataPanel,
  measureIndexForPlaybackTime,
  PerformancePlaybackPanel,
  preferredPracticeMode,
  PracticePlaybackPanel,
  ResultCard,
  RuntimePanel,
  ScorePreviewSection,
  UploadPanel,
} from './App';
import type {
  JobStatusResponse,
  LocalDataSummaryResponse,
  RuntimePreflightResponse,
  TranscriptionJobSummary,
  TranscriptionResultResponse,
} from './services/types';

const unsafeTokens = [
  '/Users/',
  '/tmp/',
  '/private/tmp/',
  '/var/folders/',
  'traceback',
  'stdout',
  'stderr',
  'raw command',
  'command_template',
];

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
    source_job_id: null,
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
    review_timeline: {
      schema_version: '1.0',
      timing_source: 'score_tempo',
      tempo_bpm: 120,
      audio_sources: [
        { kind: 'original', label: '原始音訊', available: true, playback_url: '/api/v1/transcriptions/job-1/review-audio/original' },
        { kind: 'drums_stem', label: '分離鼓聲', available: true, playback_url: '/api/v1/transcriptions/job-1/review-audio/drums_stem' },
      ],
      measures: [
        {
          measure_index: 1,
          start_seconds: 0,
          end_seconds: 2,
          render_kind: 'groove',
          drum_counts: { closed_hat: 8, kick: 2, snare: 2 },
          warnings: [],
        },
        {
          measure_index: 2,
          start_seconds: 2,
          end_seconds: 4,
          render_kind: 'groove',
          drum_counts: { closed_hat: 8, kick: 2, snare: 2 },
          warnings: [],
        },
      ],
      performance_playback: {
        available: true,
        event_count: 4,
        events: [
          { time_seconds: 0, drum: 'kick', velocity: 100 },
          { time_seconds: 0.5, drum: 'closed_hat', velocity: 68 },
          { time_seconds: 1, drum: 'snare', velocity: 96 },
          { time_seconds: 2.5, drum: 'open_hat', velocity: 72 },
        ],
      },
    },
    pipeline: {
      mode: 'mock',
      status: 'completed',
      config: {
        mode: 'demo_mock',
        adtof_threshold_preset: null,
        tom_filter_preset: null,
        runtime_fallback_status: 'not_required',
        source_job_id: null,
      },
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
        notation_readability: {
          layout_profile: 'standard_drum_v1',
          voice_count: 2,
          has_hand_voice: true,
          has_foot_voice: true,
          hand_event_count: 3,
          foot_event_count: 2,
          generic_tom_count: 0,
          measure_count: 4,
          dense_measure_count: 0,
          dense_measure_threshold: 24,
          warnings: [],
        },
        notation_chart: {
          mode: 'readable_drum_chart_v2',
          readability_verdict: 'readable_chart_candidate',
          original_event_count: 7,
          chart_event_count: 5,
          max_events_per_measure: 8,
          max_visible_notes_per_measure: 5,
          measure_count: 4,
          groove_measure_count: 4,
          repeat_measure_count: 0,
          fill_measure_count: 0,
          accent_measure_count: 0,
          preserved_counts: { closed_hat: 2, kick: 2, snare: 1 },
          dropped_counts: {},
          dense_measures_before: 0,
          dense_measures_after: 0,
          warnings: [],
        },
        quality_flags: ['sparse_transcription'],
        warnings: ['sparse_transcription'],
        postprocess_filters: {},
        quality_verdict: {
          verdict: 'unknown',
          usability_score: null,
          limitations: ['quality_verdict_unavailable'],
          candidate_gate: {
            status: 'unknown',
            run_completed: null,
            processed_event_count: null,
            min_event_count: null,
            kick_present: null,
            snare_present: null,
            hihat_present: null,
            blocking_flags: [],
            musicxml_available: true,
            musicxml_parseable: true,
          },
          musicxml_available: true,
          musicxml_parseable: true,
        },
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
    source_result_summary: null,
    ...overrides,
  };
}

function candidateResultFixture(): TranscriptionResultResponse {
  const base = resultFixture();
  const candidateTimeline = {
    ...base.review_timeline!,
    audio_sources: [
      ...base.review_timeline!.audio_sources,
      { kind: 'accompaniment', label: '去鼓後伴奏', available: true, playback_url: '/api/v1/transcriptions/job-1/review-audio/accompaniment' },
    ],
  };
  return resultFixture({
    pipeline: {
      ...base.pipeline!,
      mode: 'true_ai',
      candidate_analysis: {
        schema_version: '1.0',
        status: 'completed',
        recommended_candidate_id: 'threshold_0_4',
        candidates: [
          {
            candidate_id: 'threshold_0_4',
            rank: 1,
            position: 2,
            status: 'completed',
            selected: true,
            config: { threshold: 0.4, adtof_threshold_preset: 'separated_v1', tom_filter_preset: 'tom_guard_v1' },
            recommendation: { score: 82, recommendation: 'recommended_for_practice', reasons: ['節奏與譜面結構相對穩定'], rejected: false },
            preview: { musicxml_url: '/api/v1/transcriptions/job-1/candidates/threshold_0_4/download/musicxml' },
            exports: [
              { type: 'midi', status: 'available', download_url: '/api/v1/transcriptions/job-1/candidates/threshold_0_4/download/midi' },
              { type: 'musicxml', status: 'available', download_url: '/api/v1/transcriptions/job-1/candidates/threshold_0_4/download/musicxml' },
              { type: 'pdf', status: 'failed', download_url: null },
            ],
            quality: base.pipeline!.quality!,
            validation: base.pipeline!.validation!,
            review_timeline: candidateTimeline,
          },
        ],
      },
    },
  });
}

function jobSummaryFixture(overrides: Partial<TranscriptionJobSummary> = {}): TranscriptionJobSummary {
  return {
    job_id: 'job-1',
    source_job_id: null,
    title: 'Demo Groove',
    file_name: 'demo.wav',
    status: 'completed',
    stage: 'completed',
    progress: 100,
    created_at: '2026-07-02T00:00:00Z',
    completed_at: '2026-07-02T00:01:00Z',
    failed_at: null,
    exports: { midi: 'available', musicxml: 'available', pdf: 'failed' },
    pipeline_config: {
      mode: 'demo_mock',
      adtof_threshold_preset: null,
      tom_filter_preset: null,
      runtime_fallback_status: 'not_required',
      source_job_id: null,
    },
    error: null,
    ...overrides,
  };
}

function localDataFixture(overrides: Partial<LocalDataSummaryResponse> = {}): LocalDataSummaryResponse {
  return {
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
    ...overrides,
  };
}

describe('local app smoke rendering', () => {
  it('can render the app shell without browser globals during static rendering', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('本機鼓譜轉寫工作台');
    expect(html).toContain('Runtime 尚未完成檢查');
    expectPublicSafe(html);
  });

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
    expectPublicSafe(html);
    expect(html).not.toContain('check_ai_runtime.py');
  });

  it('explains degraded runtime and ADTOF repair steps without raw local paths', () => {
    const html = renderToStaticMarkup(
      <RuntimePanel runtime={runtimeFixture()} loading={false} error={null} onRefresh={() => undefined} />,
    );

    expect(html).toContain('Mock pipeline 可用');
    expect(html).toContain('true AI runtime 尚未 ready');
    expect(html).toContain('true AI smoke 需另行 opt-in');
    expect(html).toContain('先執行 normalize 與 Demucs separation');
    expect(html).toContain('GROOVESCRIBE_ADTOF_VERIFY_INPUT');
    expectPublicSafe(html);
  });

  it('shows local launch guidance when runtime preflight cannot reach backend', () => {
    const html = renderToStaticMarkup(
      <RuntimePanel
        runtime={null}
        loading={false}
        error="Failed to fetch"
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain('Failed to fetch');
    expect(html).toContain('npm run dev:local');
    expect(html).toContain('npm run check:local');
    expectPublicSafe(html);
  });

  it('keeps upload available for degraded mock-ready runtime', () => {
    const html = renderToStaticMarkup(
      <UploadPanel
        canUpload
        uploading={false}
        selectedFile={{ name: 'demo.wav' } as File}
        title=""
        pipelineMode="demo_mock"
        runtime={runtimeFixture()}
        trueAiReady={false}
        onFileChange={() => undefined}
        onTitleChange={() => undefined}
        onPipelineModeChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(html).toContain('開始本機分析');
    expect(html).toContain('Demo mode');
    expect(html).toContain('True-AI runtime 尚未 ready');
    expect(html).not.toContain('<button class="primaryButton" type="submit" disabled=""');
  });

  it('shows the true-AI V1 product preset when runtime is ready', () => {
    const html = renderToStaticMarkup(
      <UploadPanel
        canUpload
        uploading={false}
        selectedFile={{ name: 'demo.mp3' } as File}
        title=""
        pipelineMode="true_ai"
        runtime={runtimeFixture({ status: 'ready', true_ai_ready: true })}
        trueAiReady
        onFileChange={() => undefined}
        onTitleChange={() => undefined}
        onPipelineModeChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(html).toContain('True-AI V1 preset');
    expect(html).toContain('separated_v1');
    expect(html).toContain('tom_guard_v1');
    expectPublicSafe(html);
  });

  it('keeps upload disabled when runtime is not ready', () => {
    const html = renderToStaticMarkup(
      <UploadPanel
        canUpload={false}
        uploading={false}
        selectedFile={{ name: 'demo.wav' } as File}
        title=""
        pipelineMode="demo_mock"
        runtime={runtimeFixture({ status: 'not_ready', mock_ai_ready: false })}
        trueAiReady={false}
        onFileChange={() => undefined}
        onTitleChange={() => undefined}
        onPipelineModeChange={() => undefined}
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
    expect(html).toContain('Pipeline config');
    expect(html).toContain('Demo / mock');
    expect(html).toContain('自動交付包');
    expect(html).not.toContain('音訊對照修譜');
    expect(html).not.toContain('/api/v1/transcriptions/job-1/review-audio/original');
    expect(html).not.toContain('/tmp/');
    expect(html).toContain('/api/v1/transcriptions/job-1/review-packet');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/review-packet');
    expect(html).toContain('quality summary');
    expect(html).toContain('performance artifacts');
    expect(html).toContain('Raw events');
    expect(html).toContain('Processed events');
    expect(html).toContain('closed_hat: 2');
    expect(html).toContain('sparse_transcription');
    expect(html).toContain('品質狀態未知');
    expect(html).toContain('尚未產生品質判斷');
    expect(html).toContain('Demo/mock 結果僅供流程驗證');
    expect(html).toContain('不代表真實音檔轉譜品質');
    expect(html).toContain('瀏覽器內試聽');
    expect(html).toContain('播放鼓譜');
    expect(html).toContain('重播');
    expect(html).toContain('音量');
    expect(html).toContain('45%');
    expect(html).toContain('待播放');
    expect(html).toContain('雙聲部鼓譜');
    expect(html).toContain('可讀鼓譜 5/7');
    expect(html).toContain('Midi Post Processing');
    expect(html).toContain('mock_ai_enabled');
    expect(html).toContain('5 events');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/midi');
    expect(html).toContain('/api/v1/transcriptions/job-1/download/musicxml');
    expect(html).toContain('PDF');
    expect(html).toContain('failed');
    expect(html).toContain('failed · optional');
    expect(html).not.toContain('href="#"');
    expectPublicSafe(html);
  });

  it('renders browser playback controls only when performance events are available', () => {
    const html = renderToStaticMarkup(<PerformancePlaybackPanel timeline={resultFixture().review_timeline} />);
    const unavailableHtml = renderToStaticMarkup(
      <PerformancePlaybackPanel
        timeline={{
          ...resultFixture().review_timeline!,
          performance_playback: { available: false, event_count: 0, events: [] },
        }}
      />,
    );

    expect(html).toContain('瀏覽器內試聽');
    expect(html).toContain('使用 simplified performance chart');
    expect(html).toContain('播放鼓譜');
    expect(html).toContain('重播');
    expect(html).toContain('音量');
    expect(html).toContain('aria-label="試聽音量"');
    expect(html).toContain('45%');
    expect(html).toContain('待播放');
    expect(unavailableHtml).toBe('');
    expectPublicSafe(html);
  });

  it('renders the beginner candidate recommendation and synchronized practice modes', () => {
    const result = candidateResultFixture();
    const html = renderToStaticMarkup(<ResultCard result={result} selectedCandidateId="threshold_0_4" />);
    const playbackHtml = renderToStaticMarkup(<PracticePlaybackPanel timeline={result.pipeline!.candidate_analysis!.candidates[0].review_timeline} />);

    expect(html).toContain('推薦用於練習');
    expect(html).toContain('版本 1');
    expect(html).toContain('技術診斷');
    expect(html).toContain('/candidates/threshold_0_4/download/midi');
    expect(playbackHtml).toContain('原曲');
    expect(playbackHtml).toContain('鼓譜單獨');
    expect(playbackHtml).toContain('伴奏加鼓譜');
    expect(playbackHtml).toContain('播放位置');
    expectPublicSafe(html);
    expectPublicSafe(playbackHtml);
  });

  it('keeps a hard-rejected canonical candidate inspectable without presenting it as recommended', () => {
    const result = candidateResultFixture();
    const analysis = result.pipeline!.candidate_analysis!;
    analysis.recommended_candidate_id = null;
    analysis.canonical_candidate_id = 'threshold_0_4';
    analysis.candidates[0].selected = true;
    analysis.candidates[0].recommendation = {
      score: 0,
      recommendation: 'reanalyze_recommended',
      reasons: ['自動檢查未達適合練習的門檻'],
      rejected: true,
    };
    analysis.candidates[0].validation = {
      musicxml: { available: true, parseable: true, error_code: null, warnings: ['candidate_preview_only'] },
      pdf: { available: false, optional: true, openable: null, error_code: 'pdf_unavailable', warnings: [] },
    };

    const html = renderToStaticMarkup(<ResultCard result={result} selectedCandidateId={null} />);
    const previewHtml = renderToStaticMarkup(<ScorePreviewSection result={result} selectedCandidateId={null} />);

    expect(html).toContain('不建議使用，建議重新分析');
    expect(html).toContain('/candidates/threshold_0_4/download/midi');
    expect(html).not.toContain('推薦用於練習');
    expect(previewHtml).toContain('候選 1 · 不建議使用，建議重新分析');
    expect(previewHtml).toContain('candidate_preview_only');
  });

  it('keeps practice playback useful when an accompaniment stem is unavailable', () => {
    const html = renderToStaticMarkup(
      <PracticePlaybackPanel
        timeline={{
          ...resultFixture().review_timeline!,
          audio_sources: [{ kind: 'original', label: '原始音訊', available: true, playback_url: '/api/v1/transcriptions/job-1/review-audio/original' }],
        }}
      />,
    );

    expect(html).toContain('伴奏 stem 未取得');
    expect(html).toContain('原曲');
    expect(html).toContain('鼓譜單獨');
    expectPublicSafe(html);
  });

  it('defaults legacy audio-only results to the original track instead of silent chart playback', () => {
    const timeline = {
      ...resultFixture().review_timeline!,
      performance_playback: { available: false, event_count: 0, events: [] },
      audio_sources: [{ kind: 'original', label: '原始音訊', available: true, playback_url: '/api/v1/transcriptions/job-1/review-audio/original' }],
    };
    const html = renderToStaticMarkup(<PracticePlaybackPanel timeline={timeline} />);

    expect(preferredPracticeMode(false, true)).toBe('original');
    expect(preferredPracticeMode(true, true)).toBe('chart');
    expect(html).toContain('class="selected">原曲');
    expect(html).toContain('播放');
  });

  it('keeps an expired playback session from cleaning up the active session', () => {
    expect(isCurrentPlaybackSession(4, 4)).toBe(true);
    expect(isCurrentPlaybackSession(5, 4)).toBe(false);
  });

  it('does not let a delayed old audio-context failure clean up a newer playback session', async () => {
    let rejectOldResume: ((reason?: unknown) => void) | undefined;
    const oldResume = new Promise<void>((_resolve, reject) => { rejectOldResume = reject; });
    let activeSession = 1;
    let oldCloseCount = 0;
    let newCloseCount = 0;
    let clearCount = 0;
    let pauseCount = 0;
    let releaseCount = 0;
    const oldContext = { close: async () => { oldCloseCount += 1; } } as Pick<AudioContext, 'close'>;
    const newContext = { close: async () => { newCloseCount += 1; } } as Pick<AudioContext, 'close'>;

    const oldFailure = oldResume.catch(() => cleanupFailedChartStart({
      activeSession,
      failedSession: 1,
      failedContext: oldContext,
      activeContext: newContext,
      clearScheduled: () => { clearCount += 1; },
      releaseActiveContext: () => { releaseCount += 1; },
      pauseAudio: () => { pauseCount += 1; },
    }));
    activeSession = 2;
    rejectOldResume?.(new Error('resume rejected'));

    await expect(oldFailure).resolves.toBe(false);
    expect(oldCloseCount).toBe(1);
    expect(newCloseCount).toBe(0);
    expect(clearCount).toBe(0);
    expect(pauseCount).toBe(0);
    expect(releaseCount).toBe(0);
  });

  it('cleans up audio and scheduling when the current chart session cannot start', () => {
    let closeCount = 0;
    let clearCount = 0;
    let pauseCount = 0;
    let releaseCount = 0;
    const context = { close: async () => { closeCount += 1; } } as Pick<AudioContext, 'close'>;

    expect(cleanupFailedChartStart({
      activeSession: 3,
      failedSession: 3,
      failedContext: context,
      activeContext: context,
      clearScheduled: () => { clearCount += 1; },
      releaseActiveContext: () => { releaseCount += 1; },
      pauseAudio: () => { pauseCount += 1; },
    })).toBe(true);
    expect(closeCount).toBe(1);
    expect(clearCount).toBe(1);
    expect(pauseCount).toBe(1);
    expect(releaseCount).toBe(1);
  });

  it('keeps browser playback mute and measure helpers predictable', () => {
    const measures = resultFixture().review_timeline!.measures;

    expect(drumPreviewIntensity(100, 0)).toBe(0);
    expect(drumPreviewIntensity(0, 0.45)).toBeGreaterThan(0);
    expect(drumPreviewIntensity(127, 1)).toBe(1);
    expect(measureIndexForPlaybackTime(measures, 0.5)).toBe(1);
    expect(measureIndexForPlaybackTime(measures, 2.5)).toBe(2);
    expect(measureIndexForPlaybackTime([], 2.5)).toBeNull();
    expect(elapsedPlaybackSeconds(12_000, 12_750)).toBe(0.75);
    expect(elapsedPlaybackSeconds(12_000, 11_000)).toBe(0);
  });

  it('derives safe BPM and deterministic practice speed values', () => {
    const timeline = resultFixture().review_timeline!;

    expect(practiceBaseBpm(timeline, 90, 80)).toBe(120);
    expect(practiceBaseBpm({ ...timeline, tempo_bpm: null }, 90, 80)).toBe(90);
    expect(formatEffectiveBpm(120, 0.75)).toBe('90');
    expect(formatEffectiveBpm(123, 1.25)).toBe('153.8');
    expect(nearestPlaybackRate(1.1)).toBe(1);
    expect(playbackElapsedSeconds(1000, 3000, 1.5)).toBe(3);
  });

  it('keeps only artifact-complete practice modes enabled', () => {
    expect(practiceModes({ original: true, drums: true, accompaniment: true, hasChart: true })).toEqual(['chart', 'original', 'accompaniment']);
    expect(practiceModes({ original: true, drums: false, accompaniment: true, hasChart: true })).toEqual(['original', 'accompaniment']);
    expect(practiceModes({ original: false, drums: true, accompaniment: true, hasChart: false })).toEqual([]);
  });

  it('renders score preview in a full-width section with validation fallback', () => {
    const html = renderToStaticMarkup(<ScorePreviewSection result={resultFixture()} />);

    expect(html).toContain('鼓譜滿版預覽');
    expect(html).toContain('Demo Groove');
    expect(html).toContain('MusicXML preview');
    expect(html).toContain('fullWidthPreview');
    expect(html).toContain('MusicXML validation');
    expect(html).toContain('parseable');
    expect(html).toContain('PDF validation');
    expect(html).toContain('optional unavailable');
    expect(html).toContain('pdf_optional_unavailable');
    expectPublicSafe(html);
  });

  it('does not reserve a full-height score canvas when preview is unavailable', () => {
    const html = renderToStaticMarkup(
      <ScorePreviewSection
        result={resultFixture({
          preview: { musicxml_url: null },
        })}
      />,
    );

    expect(html).toContain('鼓譜滿版預覽');
    expect(html).toContain('MusicXML preview unavailable');
    expect(html).not.toContain('musicXmlCanvas');
    expectPublicSafe(html);
  });

  it('shows concrete next steps for low-quality true-AI results', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            mode: 'true_ai',
            config: {
              ...resultFixture().pipeline!.config!,
              mode: 'true_ai',
              adtof_threshold_preset: 'separated_v1',
              tom_filter_preset: 'tom_guard_v1',
            },
            quality: {
              ...resultFixture().pipeline!.quality!,
              quality_verdict: {
                ...resultFixture().pipeline!.quality!.quality_verdict!,
                usability_score: 2,
                limitations: ['sparse_transcription'],
                candidate_gate: {
                  ...resultFixture().pipeline!.quality!.quality_verdict!.candidate_gate,
                  status: 'failed',
                  blocking_flags: ['sparse_transcription'],
                },
              },
              performance_gate: {
                schema_version: '1.0',
                verdict: 'needs_better_source',
                delivery_allowed: false,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'technical_artifacts_only',
                blocking_issues: ['sparse_transcription'],
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('TRUE AI');
    expect(html).toContain('True-AI 結果需要人工修譜或重新嘗試');
    expect(html).toContain('主要 blocker');
    expect(html).toContain('執行 real audio pilot / quality matrix');
    expect(html).not.toContain('Demo/mock 結果僅供流程驗證');
    expectPublicSafe(html);
  });

  it('labels an unverified performance score conservatively and keeps a not-ready score out of primary downloads', () => {
    const lowConfidenceHtml = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              performance_gate: {
                schema_version: '1.0',
                verdict: 'playable_but_low_confidence',
                delivery_allowed: false,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'playable_draft_unverified',
                blocking_issues: ['gate_calibration_not_ready'],
                midi: { playback_ready: true },
                musicxml: { parseable: true },
                rhythm: { complete: true },
                playability: { core_groove_stable: true },
                audio_alignment: { status: 'measured', onset_alignment_rate: 0.82 },
              },
            },
          },
        })}
      />,
    );
    const notReadyHtml = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              performance_gate: {
                schema_version: '1.0',
                verdict: 'not_ready',
                delivery_allowed: false,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'technical_artifacts_only',
                blocking_issues: ['core_drum_missing'],
                midi: { playback_ready: true },
                musicxml: { parseable: true },
                rhythm: { complete: true },
                playability: { core_groove_stable: false },
                audio_alignment: { status: 'measured', onset_alignment_rate: 0.82 },
              },
            },
          },
        })}
      />,
    );

    expect(lowConfidenceHtml).toContain('可播放草稿，未完成對照驗證');
    expect(lowConfidenceHtml).toContain('未完成真實音訊對照驗證');
    expect(lowConfidenceHtml).toContain('Drum Draft MIDI');
    expect(lowConfidenceHtml).toContain('Drum Draft MusicXML');
    expect(notReadyHtml).toContain('技術診斷 artifacts');
    expect(notReadyHtml).not.toContain('/api/v1/transcriptions/job-1/download/midi');
    expect(notReadyHtml).not.toContain('/api/v1/transcriptions/job-1/download/musicxml');
    expectPublicSafe(lowConfidenceHtml);
    expectPublicSafe(notReadyHtml);
  });

  it('renders legacy performance gates without blocking issues', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              performance_gate: {
                schema_version: '1.0',
                verdict: 'playable_but_low_confidence',
                delivery_allowed: false,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'playable_draft_unverified',
                midi: { playback_ready: true },
                musicxml: { parseable: true },
                rhythm: { complete: true },
                playability: { core_groove_stable: true },
                audio_alignment: { status: 'measured', onset_alignment_rate: 0.82 },
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('可播放，但系統信心不足');
    expect(html).toContain('已通過可播放與結構檢查');
    expect(html).not.toContain('系統限制');
    expectPublicSafe(html);
  });

  it('labels a calibrated performance-ready score consistently and names PDF exports correctly', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          exports: [
            ...resultFixture().exports.slice(0, 2),
            {
              type: 'pdf',
              status: 'available',
              content_type: 'application/pdf',
              file_size_bytes: 512,
              checksum: 'pdf-checksum',
              download_url: '/api/v1/transcriptions/job-1/download/pdf',
            },
          ],
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              performance_gate: {
                schema_version: '1.0',
                verdict: 'performance_ready',
                delivery_allowed: true,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'verified_performance_score',
                blocking_issues: [],
                midi: { playback_ready: true },
                musicxml: { parseable: true },
                rhythm: { complete: true },
                playability: { core_groove_stable: true },
                audio_alignment: { status: 'measured', onset_alignment_rate: 0.92 },
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('可直接演奏');
    expect(html).toContain('已通過已校準自動交付驗證');
    expect(html).toContain('Performance MIDI');
    expect(html).toContain('Performance MusicXML');
    expect(html).toContain('Performance PDF');
    expect(html).not.toContain('未完成真實音訊對照驗證');
  });

  it('does not label inconsistent performance-ready gates as verified performance exports', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              performance_gate: {
                schema_version: '1.0',
                verdict: 'performance_ready',
                delivery_allowed: true,
                ground_truth_verified: false,
                real_audio_verified: false,
                delivery_status: 'technical_artifacts_only',
                blocking_issues: [],
                midi: { playback_ready: true },
                musicxml: { parseable: true },
                rhythm: { complete: true },
                playability: { core_groove_stable: true },
                audio_alignment: { status: 'measured', onset_alignment_rate: 0.92 },
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('技術診斷 artifacts');
    expect(html).toContain('可播放草稿，需人工確認');
    expect(html).toContain('未完成真實音訊對照驗證');
    expect(html).toContain('缺少 verified delivery contract');
    expect(html).not.toContain('已通過已校準自動交付驗證');
    expect(html).toContain('此交付包保留自動品質結果');
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
            config: {
              mode: 'true_ai',
              adtof_threshold_preset: 'separated_v1',
              tom_filter_preset: 'tom_guard_v1',
              runtime_fallback_status: 'not_applied',
              source_job_id: null,
            },
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
              notation_readability: {
                layout_profile: 'standard_drum_v1',
                voice_count: 2,
                has_hand_voice: true,
                has_foot_voice: true,
                hand_event_count: 6,
                foot_event_count: 1,
                generic_tom_count: 6,
                measure_count: 8,
                dense_measure_count: 2,
                dense_measure_threshold: 24,
                warnings: ['notation_dense_full_mix_likely', 'generic_tom_position_used'],
              },
              notation_chart: {
                mode: 'readable_drum_chart_v3',
                readability_verdict: 'readable_chart_candidate',
                original_event_count: 80,
                chart_event_count: 24,
                max_events_per_measure: 8,
                max_visible_notes_per_measure: 8,
                measure_count: 12,
                groove_measure_count: 8,
                repeat_measure_count: 3,
                fill_measure_count: 1,
                accent_measure_count: 1,
                anchor_measure_count: 2,
                literal_measure_count: 3,
                break_measure_count: 0,
                stable_groove_section_count: 1,
                complete_core_groove_measure_count: 6,
                incomplete_core_groove_measure_count: 2,
                hihat_rendered_measure_count: 6,
                preserved_counts: { closed_hat: 8, kick: 8, snare: 8 },
                dropped_counts: { tom: 20, cymbal: 12 },
                dense_measures_before: 4,
                dense_measures_after: 0,
                warnings: ['notation_tom_reduced_for_readability'],
              },
              quality_flags: ['hihat_missing_likely', 'mostly_tom_output'],
              warnings: ['hihat_missing_likely', 'mostly_tom_output'],
              postprocess_filters: {
                tom_false_positive: {
                  enabled: true,
                  preset: 'tom_guard_v1',
                  status: 'applied',
                  input_tom_count: 6,
                  output_tom_count: 4,
                  dropped_tom_count: 2,
                  target_max_tom_ratio: 0.3,
                  input_event_count: 18,
                  output_event_count: 16,
                },
              },
              quality_verdict: {
                verdict: 'draft_candidate_needs_review',
                usability_score: 3,
                limitations: ['tom_false_positive_likely'],
                candidate_gate: {
                  status: 'passed',
                  run_completed: true,
                  processed_event_count: 7,
                  min_event_count: 4,
                  kick_present: true,
                  snare_present: true,
                  hihat_present: true,
                  blocking_flags: [],
                  musicxml_available: true,
                  musicxml_parseable: false,
                },
                musicxml_available: true,
                musicxml_parseable: false,
              },
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
              visual_qa: {
                status: 'musescore_gui_session_unavailable',
                reason_code: 'musescore_gui_session_unavailable',
                pdf_available: false,
                first_page_png_available: false,
              },
            },
            pipeline_log_available: true,
          },
        })}
      />,
    );

    expect(html).toContain('TRUE AI');
    expect(html).toContain('separated_v1');
    expect(html).toContain('tom_guard_v1');
    expect(html).toContain('草稿品質仍需提升');
    expect(html).toContain('3/5');
    expect(html).toContain('Tom 誤判偏多');
    expect(html).toContain('已套用 tom filter');
    expect(html).toContain('譜面偏密，系統不建議直接交付');
    expect(html).toContain('這份 full-mix 譜面仍偏密；系統會保留技術 artifacts，但不應視為完成 performance score。');
    expect(html).toContain('Tom 位置使用保守通用表示；目前不會宣稱其細節已自動驗證。');
    expect(html).toContain('逐小節可讀鼓譜 24/80');
    expect(html).toContain('MusicXML 已使用逐小節可讀鼓譜；完整 processed events 仍保留於 MIDI。');
    expect(html).toContain('每小節實寫簡化鼓譜');
    expect(html).toContain('完整 core groove：6');
    expect(html).toContain('Hi-hat 小節：6');
    expect(html).toContain('需檢查');
    expect(html).toContain('Drum Transcription');
    expect(html).toContain('hihat_missing_likely');
    expect(html).toContain('tom: 6');
    expectPublicSafe(html);
  });

  it('renders missing validation as not reported for backward-compatible score previews', () => {
    const html = renderToStaticMarkup(<ScorePreviewSection result={resultFixture({ pipeline: null })} />);

    expect(html).toContain('MusicXML preview');
    expect(html).toContain('MusicXML validation');
    expect(html).toContain('PDF validation');
    expect(html).toContain('not reported');
    expect(html).not.toContain('pipeline.validation');
    expectPublicSafe(html);
  });

  it('renders legacy pipeline summary without quality blocks', () => {
    const legacyResult = resultFixture({
      pipeline: {
        mode: 'unknown',
        status: 'completed',
        config: {
          mode: 'unknown',
          adtof_threshold_preset: null,
          tom_filter_preset: null,
          runtime_fallback_status: null,
          source_job_id: null,
        },
        stages: [],
        artifacts: [],
        warnings: [],
        pipeline_log_available: false,
      },
    });
    const html = renderToStaticMarkup(
      <ResultCard
        result={legacyResult}
      />,
    );
    const scoreHtml = renderToStaticMarkup(<ScorePreviewSection result={legacyResult} />);

    expect(html).toContain('Pipeline summary');
    expect(html).toContain('log unavailable');
    expect(scoreHtml).toContain('MusicXML validation');
    expect(scoreHtml).toContain('not reported');
    expect(html).not.toContain('Raw events');
    expectPublicSafe(html);
    expectPublicSafe(scoreHtml);
  });

  it('renders unknown quality verdict without crashing', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              quality_verdict: {
                verdict: 'unknown',
                usability_score: null,
                limitations: ['quality_verdict_unavailable'],
                candidate_gate: {
                  status: 'unknown',
                  run_completed: null,
                  processed_event_count: null,
                  min_event_count: null,
                  kick_present: null,
                  snare_present: null,
                  hihat_present: null,
                  blocking_flags: [],
                  musicxml_available: true,
                  musicxml_parseable: true,
                },
                musicxml_available: true,
                musicxml_parseable: true,
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('品質狀態未知');
    expect(html).toContain('未評分');
    expect(html).toContain('尚未產生品質判斷');
    expectPublicSafe(html);
  });

  it('renders tom filter still-high status without raw JSON', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          pipeline: {
            ...resultFixture().pipeline!,
            quality: {
              ...resultFixture().pipeline!.quality!,
              postprocess_filters: {
                tom_false_positive: {
                  enabled: true,
                  preset: 'tom_guard_v1',
                  status: 'no_safe_tom_filter_change',
                  input_tom_count: 7,
                  output_tom_count: 7,
                  dropped_tom_count: 0,
                  target_max_tom_ratio: 0.3,
                },
              },
            },
          },
        })}
      />,
    );

    expect(html).toContain('Tom filter');
    expect(html).toContain('Tom 誤判仍偏多');
    expect(html).not.toContain('no_safe_tom_filter_change');
    expectPublicSafe(html);
  });

  it('renders rerun comparison without exposing artifact paths', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        trueAiReady
        result={resultFixture({
          source_job_id: 'job-source',
          source_result_summary: {
            job_id: 'job-source',
            status: 'completed',
            pipeline_config: {
              mode: 'demo_mock',
              adtof_threshold_preset: null,
              tom_filter_preset: null,
              runtime_fallback_status: 'not_required',
              source_job_id: null,
            },
            quality_verdict: {
              verdict: 'draft_candidate_needs_review',
              usability_score: 3,
              limitations: ['tom_false_positive_likely'],
            },
            processed_drum_counts: { kick: 3, snare: 3, tom: 7 },
            tom_filter: null,
            musicxml_parseable: true,
          },
        })}
        onRerun={() => undefined}
      />,
    );

    expect(html).toContain('沿用設定重跑');
    expect(html).toContain('True-AI V1');
    expect(html).toContain('與前一次比較');
    expect(html).toContain('Previous tom');
    expect(html).toContain('Current tom');
    expectPublicSafe(html);
  });

  it('renders missing source comparison summary without crashing', () => {
    const html = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          source_job_id: 'missing-source',
          source_result_summary: {
            job_id: 'missing-source',
            status: 'missing',
            quality_verdict: null,
            tom_filter: null,
            musicxml_parseable: null,
          },
        })}
      />,
    );

    expect(html).toContain('與前一次比較');
    expect(html).toContain('missing-source');
    expect(html).toContain('Previous verdict');
    expect(html).toContain('unknown');
    expect(html).toContain('Previous tom');
    expect(html).toContain('需檢查');
    expectPublicSafe(html);
  });

  it('renders PDF available and pending states without blocking MIDI or MusicXML', () => {
    const pdfAvailable = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          exports: [
            ...resultFixture().exports.filter((item) => item.type !== 'pdf'),
            {
              type: 'pdf',
              status: 'available',
              content_type: 'application/pdf',
              file_size_bytes: 512,
              checksum: 'pdf-checksum',
              download_url: '/api/v1/transcriptions/job-1/download/pdf',
            },
          ],
          pipeline: {
            ...resultFixture().pipeline!,
            validation: {
              musicxml: {
                available: true,
                parseable: true,
                error_code: null,
                warnings: [],
              },
              pdf: {
                available: true,
                optional: true,
                openable: true,
                error_code: null,
                warnings: [],
              },
            },
          },
        })}
      />,
    );
    expect(pdfAvailable).toContain('/api/v1/transcriptions/job-1/download/pdf');
    expect(pdfAvailable).toContain('PDF');
    expectPublicSafe(pdfAvailable);

    const pdfPending = renderToStaticMarkup(
      <ResultCard
        result={resultFixture({
          exports: [
            ...resultFixture().exports.filter((item) => item.type !== 'pdf'),
            {
              type: 'pdf',
              status: 'pending',
              content_type: 'application/pdf',
              file_size_bytes: null,
              checksum: null,
              download_url: null,
            },
          ],
        })}
      />,
    );
    expect(pdfPending).toContain('/api/v1/transcriptions/job-1/download/midi');
    expect(pdfPending).toContain('/api/v1/transcriptions/job-1/download/musicxml');
    expect(pdfPending).toContain('pending');
    expect(pdfPending).toContain('optional unavailable');
    expectPublicSafe(pdfPending);
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
    expect(html).toContain('保留舊 artifacts');
    expect(html).toContain('Progress 45%');
    expectPublicSafe(html);
  });

  it('renders retry action for failed and interrupted jobs', () => {
    const failedHtml = renderToStaticMarkup(
      <JobStatusCard
        status={{
          job_id: 'job-failed',
          status: 'failed',
          stage: 'failed',
          progress: 45,
          message: '分析失敗，請查看錯誤訊息。',
          error: {
            code: 'PIPELINE_FAILED',
            message: '音訊分析流程失敗，請稍後再試或重新上傳音檔。',
            stage: 'drum_transcription',
            retriable: true,
          },
          created_at: '2026-07-02T00:00:00Z',
        }}
        onRetry={() => undefined}
      />,
    );

    expect(failedHtml).toContain('重試');
    expect(failedHtml).toContain('true AI opt-in 失敗');
    expectPublicSafe(failedHtml);
  });

  it('renders local data summary as dry-run visibility only', () => {
    const html = renderToStaticMarkup(
      <LocalDataPanel summary={localDataFixture()} error={null} onRefresh={() => undefined} />,
    );

    expect(html).toContain('本機資料狀態');
    expect(html).toContain('Storage root');
    expect(html).toContain('storage');
    expect(html).toContain('Job dirs');
    expect(html).toContain('Orphans');
    expect(html).toContain('dry-run');
    expect(html).toContain('不會從 UI 刪除 storage 或 DB');
    expectPublicSafe(html);
  });

  it('renders job history with view retry and rerun controls', () => {
    const html = renderToStaticMarkup(
      <JobHistoryPanel
        jobs={[
          jobSummaryFixture(),
          jobSummaryFixture({
            job_id: 'job-failed',
            title: 'Failed Groove',
            status: 'failed',
            stage: 'failed',
            progress: 45,
            completed_at: null,
            failed_at: '2026-07-02T00:02:00Z',
            exports: {},
            error: {
              code: 'PIPELINE_FAILED',
              message: '音訊分析流程失敗，請稍後再試或重新上傳音檔。',
              stage: 'drum_transcription',
              retriable: true,
            },
          }),
          jobSummaryFixture({
            job_id: 'job-processing',
            title: 'Active Groove',
            status: 'processing',
            stage: 'drum_transcription',
            progress: 50,
            completed_at: null,
            exports: {},
          }),
        ]}
        loading={false}
        error={null}
        activeJobId="job-1"
        retryingJobId={null}
        onRefresh={() => undefined}
        onSelectJob={() => undefined}
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain('近期任務');
    expect(html).toContain('Demo Groove');
    expect(html).toContain('MIDI available');
    expect(html).toContain('重新執行');
    expect(html).toContain('Failed Groove');
    expect(html).toContain('重試');
    expect(html).toContain('Active Groove');
    expect(html).not.toContain('raw command');
    expectPublicSafe(html);
  });

  it('limits job history to five rows before loading more', () => {
    const jobs = Array.from({ length: 7 }, (_, index) =>
      jobSummaryFixture({
        job_id: `job-${index}`,
        title: `History Job ${index + 1}`,
      }),
    );
    const html = renderToStaticMarkup(
      <JobHistoryPanel
        jobs={jobs}
        loading={false}
        error={null}
        activeJobId={null}
        retryingJobId={null}
        onRefresh={() => undefined}
        onSelectJob={() => undefined}
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain('History Job 1');
    expect(html).toContain('History Job 5');
    expect(html).not.toContain('History Job 6');
    expect(html).not.toContain('History Job 7');
    expect(html).toContain('讀取更多');
    expect(html).toContain('尚有 2 筆');
    expectPublicSafe(html);
  });

  it('keeps an active history row visible even when it is outside the first five rows', () => {
    const jobs = Array.from({ length: 7 }, (_, index) =>
      jobSummaryFixture({
        job_id: `job-${index}`,
        title: `History Job ${index + 1}`,
      }),
    );
    const html = renderToStaticMarkup(
      <JobHistoryPanel
        jobs={jobs}
        loading={false}
        error={null}
        activeJobId="job-5"
        retryingJobId={null}
        onRefresh={() => undefined}
        onSelectJob={() => undefined}
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain('History Job 1');
    expect(html).toContain('History Job 5');
    expect(html).toContain('History Job 6');
    expect(html).not.toContain('History Job 7');
    expect(html).toContain('historyRow active');
    expect(html).toContain('尚有 1 筆');
    expectPublicSafe(html);
  });
});

function expectPublicSafe(html: string) {
  const normalized = html.toLowerCase();
  for (const unsafe of unsafeTokens) {
    expect(normalized).not.toContain(unsafe.toLowerCase());
  }
}

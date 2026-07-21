import { expect, test, type Page, type Route } from '@playwright/test';
import path from 'node:path';

const JOB_ID = 'job-browser-smoke';
const checkedAt = '2026-07-03T00:00:00Z';
const createdAt = '2026-07-03T00:00:05Z';
const completedAt = '2026-07-03T00:00:07Z';
const failedAt = '2026-07-03T00:00:08Z';

test('mock browser smoke reaches result review without leaking local diagnostics', async ({ page }) => {
  const apiMetrics = await installMockApi(page);

  await page.goto('/');

  await expect(page.getByText('Mock pipeline 可用')).toBeVisible();
  await expect(page.getByText('true AI runtime 尚未 ready')).toBeVisible();

  const fixturePath = path.resolve('tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav');
  await page.getByLabel('Title').fill('Browser Smoke');
  await page.locator('input[type="file"]').setInputFiles(fixturePath);

  const uploadButton = page.getByRole('button', { name: '開始本機分析' });
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();

  await expect(page.getByText('Browser Smoke')).toBeVisible();
  await expect(page.getByText('Pipeline summary')).toBeVisible();
  await expect(page.getByText('自動交付包')).toBeVisible();
  await expect(page.getByRole('link', { name: /JSON/i })).toHaveAttribute(
    'href',
    /\/api\/v1\/transcriptions\/job-browser-smoke\/review-packet$/,
  );
  await expect(page.getByRole('link', { name: /ZIP/i })).toHaveAttribute(
    'href',
    /\/api\/v1\/transcriptions\/job-browser-smoke\/download\/review-packet$/,
  );
  await expect(page.getByText('quality summary')).toBeVisible();
  await expect(page.getByRole('link', { name: /ZIP performance artifacts/i })).toBeVisible();
  await expect(page.getByText('failed · optional').first()).toBeVisible();
  await expect(page.getByText('分析完成。')).toBeVisible();
  await expect(page.getByText('MusicXML preview', { exact: true })).toBeVisible();
  await expect(page.getByText('MusicXML preview unavailable')).toBeVisible();
  await expect(page.getByText('MusicXML validation')).toBeVisible();
  await expect(page.getByText('PDF validation')).toBeVisible();
  await expect(page.getByText('optional unavailable').first()).toBeVisible();
  await expect(page.getByText('近期任務')).toBeVisible();
  await expect(page.locator('.historyRow').filter({ hasText: 'Browser Smoke' }).first()).toBeVisible();
  await expect(page.locator('.historyRow').filter({ hasText: 'MIDI available' }).first()).toBeVisible();
  await expect(page.getByText('本機資料狀態')).toBeVisible();
  await expect(page.getByText('dry-run 可視狀態')).toBeVisible();

  const midiDownload = page.getByRole('link', { name: /MIDI/i });
  const musicXmlDownload = page.getByRole('link', { name: /MUSICXML/i });
  await expect(midiDownload).toBeVisible();
  await expect(midiDownload).toHaveAttribute('href', /\/api\/v1\/transcriptions\/job-browser-smoke\/download\/midi$/);
  await expect(musicXmlDownload).toBeVisible();
  await expect(musicXmlDownload).toHaveAttribute(
    'href',
    /\/api\/v1\/transcriptions\/job-browser-smoke\/download\/musicxml$/,
  );

  await expect(page.locator('.exportRow').filter({ hasText: 'PDF' }).filter({ hasText: 'failed' }).first()).toBeVisible();

  await expectPublicSafe(page);

  expect(apiMetrics.uploadRequests).toBe(1);
  expect(apiMetrics.statusRequests).toBeGreaterThanOrEqual(2);
  expect(apiMetrics.resultRequests).toBe(1);
  expect(apiMetrics.listRequests).toBeGreaterThanOrEqual(1);
  expect(apiMetrics.localDataRequests).toBeGreaterThanOrEqual(1);

  await page.getByRole('button', { name: '沿用設定重跑' }).click();
  await expect(page.getByText('任務已重新排入本機分析佇列。')).toBeVisible();
  await expect(page.locator('.statusCard .statusPill', { hasText: 'queued' })).toBeVisible();
  expect(apiMetrics.retryRequests).toBe(1);
});

test('candidate practice workspace defaults to a recommendation and exposes safe practice controls', async ({ page }) => {
  await installMockApi(page, { candidateAnalysis: true });
  await page.goto('/');
  await page.getByLabel('Title').fill('Candidate Practice');
  await page.locator('input[type="file"]').setInputFiles(path.resolve('tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav'));
  await page.getByRole('button', { name: '開始本機分析' }).click();

  await expect(page.getByText('推薦用於練習').first()).toBeVisible();
  await expect(page.getByRole('button', { name: /版本 1/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /版本 2/ })).toBeVisible();
  await expect(page.getByText('同步練習 / 瀏覽器內試聽')).toBeVisible();
  await expect(page.getByRole('button', { name: '原曲' })).toBeVisible();
  await expect(page.getByRole('button', { name: '鼓譜單獨' })).toBeVisible();
  await expect(page.getByRole('button', { name: '伴奏加鼓譜' })).toBeVisible();
  await expect(page.getByRole('link', { name: /MIDI.*此候選版本/i })).toHaveAttribute(
    'href',
    /\/api\/v1\/transcriptions\/job-browser-smoke\/candidates\/threshold_0_4\/download\/midi$/,
  );
  const practice = page.locator('.practicePlaybackPanel');
  await expect(practice.getByText('基準 120 BPM')).toBeVisible();
  await expect(practice.getByText('有效 120 BPM')).toBeVisible();
  await practice.getByRole('button', { name: '0.75×' }).click();
  await expect(practice.getByRole('button', { name: '0.75×' })).toHaveClass(/selected/);
  await expect(practice.getByText('有效 90 BPM')).toBeVisible();
  await practice.getByRole('button', { name: '原曲' }).click();
  await expect(practice.getByRole('button', { name: '原曲' })).toHaveClass(/selected/);
  await practice.getByRole('button', { name: '伴奏加鼓譜' }).click();
  await expect(practice.getByRole('button', { name: '伴奏加鼓譜' })).toHaveClass(/selected/);
  await practice.getByRole('button', { name: '鼓譜單獨' }).click();
  await expect(practice.getByRole('button', { name: '鼓譜單獨' })).toHaveClass(/selected/);
  await practice.locator('audio').evaluate((audio) => audio.dispatchEvent(new Event('error')));
  await expect(practice.getByText('音訊載入失敗；請改用其他播放模式或下載 MIDI。')).toBeVisible();
  await expect(practice.getByText('待播放')).toBeVisible();
  await page.getByRole('button', { name: /版本 2/ }).click();
  await expect(page.getByText('可作為參考，細節可能不準').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /MIDI.*此候選版本/i })).toHaveAttribute(
    'href',
    /\/api\/v1\/transcriptions\/job-browser-smoke\/candidates\/threshold_0_5\/download\/midi$/,
  );
  await expect(practice.getByRole('button', { name: '0.75×' })).toHaveClass(/selected/);
  await expectPublicSafe(page);
});

for (const terminalStatus of ['failed', 'interrupted'] as const) {
  test(`mock browser smoke renders ${terminalStatus} job without leaking diagnostics or downloads`, async ({ page }) => {
    const apiMetrics = await installTerminalMockApi(page, terminalStatus);

    await page.goto('/');
    await page.getByLabel('Title').fill(`Browser Smoke ${terminalStatus}`);
    await page
      .locator('input[type="file"]')
      .setInputFiles(path.resolve('tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav'));
    await page.getByRole('button', { name: '開始本機分析' }).click();

    const statusCard = page.locator('.statusCard');
    await expect(statusCard.locator('.statusPill', { hasText: terminalStatus })).toBeVisible();
    await expect(statusCard.getByText('音訊分析流程失敗，請稍後再試或重新上傳音檔。')).toBeVisible();
    if (terminalStatus === 'interrupted') {
      await expect(statusCard.getByText('本機服務曾在分析中停止')).toBeVisible();
    } else {
      await expect(statusCard.getByText('true AI opt-in 失敗')).toBeVisible();
    }

    await expect(page.getByRole('link', { name: /MIDI/i })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /MUSICXML/i })).toHaveCount(0);
    await expect(page.getByText('Pipeline summary')).toHaveCount(0);
    await expectPublicSafe(page);

    const retryButton = statusCard.getByRole('button', { name: '重試' });
    await expect(retryButton).toBeVisible();
    await retryButton.click();
    await expect(page.getByText('任務已重新排入本機分析佇列。')).toBeVisible();
    await expect(page.locator('.statusCard .statusPill', { hasText: 'queued' })).toBeVisible();
    expect(apiMetrics.retryRequests).toBe(1);

    expect(apiMetrics.uploadRequests).toBe(1);
    expect(apiMetrics.statusRequests).toBeGreaterThanOrEqual(2);
    expect(apiMetrics.resultRequests).toBe(0);
  });
}

interface MockApiMetrics {
  uploadRequests: number;
  statusRequests: number;
  resultRequests: number;
  listRequests: number;
  localDataRequests: number;
  retryRequests: number;
}

async function installMockApi(page: Page, options: { candidateAnalysis?: boolean } = {}): Promise<MockApiMetrics> {
  const metrics: MockApiMetrics = {
    uploadRequests: 0,
    statusRequests: 0,
    resultRequests: 0,
    listRequests: 0,
    localDataRequests: 0,
    retryRequests: 0,
  };

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (request.method() === 'GET' && pathname === '/api/v1/runtime/preflight') {
      return json(route, runtimePayload());
    }

    if (request.method() === 'GET' && pathname === '/api/v1/local-data/summary') {
      metrics.localDataRequests += 1;
      return json(route, localDataPayload());
    }

    if (request.method() === 'GET' && pathname === '/api/v1/transcriptions') {
      metrics.listRequests += 1;
      return json(route, {
        jobs: metrics.uploadRequests > 0 ? [historyPayload('completed')] : [],
        limit: 20,
      });
    }

    if (request.method() === 'POST' && pathname === '/api/v1/transcriptions') {
      metrics.uploadRequests += 1;
      return json(route, {
        job_id: JOB_ID,
        status: 'queued',
        status_url: `/api/v1/transcriptions/${JOB_ID}/status`,
        result_url: `/api/v1/transcriptions/${JOB_ID}`,
        created_at: createdAt,
      });
    }

    if (request.method() === 'POST' && pathname === `/api/v1/transcriptions/${JOB_ID}/retry`) {
      metrics.retryRequests += 1;
      return json(route, {
        job_id: `${JOB_ID}-rerun`,
        status: 'queued',
        status_url: `/api/v1/transcriptions/${JOB_ID}-rerun/status`,
        result_url: `/api/v1/transcriptions/${JOB_ID}-rerun`,
        created_at: createdAt,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}-rerun/status`) {
      return json(route, {
        job_id: `${JOB_ID}-rerun`,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        message: '任務已重新排入本機分析佇列。',
        error: null,
        created_at: createdAt,
        queued_at: createdAt,
        started_at: null,
        completed_at: null,
        failed_at: null,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}/status`) {
      metrics.statusRequests += 1;
      if (metrics.statusRequests === 1) {
        return json(route, {
          job_id: JOB_ID,
          status: 'processing',
          stage: 'midi_post_processing',
          progress: 75,
          message: '正在後處理 MIDI。',
          error: null,
          created_at: createdAt,
          queued_at: createdAt,
          started_at: createdAt,
          completed_at: null,
          failed_at: null,
        });
      }

      return json(route, {
        job_id: JOB_ID,
        status: 'completed',
        stage: 'completed',
        progress: 100,
        message: '分析完成。',
        error: null,
        created_at: createdAt,
        queued_at: createdAt,
        started_at: createdAt,
        completed_at: completedAt,
        failed_at: null,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}`) {
      metrics.resultRequests += 1;
      return json(route, resultPayload(options));
    }

    return json(route, { error: { code: 'NOT_MOCKED', message: `Unmocked e2e request: ${pathname}` } }, 404);
  });

  return metrics;
}

async function installTerminalMockApi(
  page: Page,
  terminalStatus: 'failed' | 'interrupted',
): Promise<MockApiMetrics> {
  const metrics: MockApiMetrics = {
    uploadRequests: 0,
    statusRequests: 0,
    resultRequests: 0,
    listRequests: 0,
    localDataRequests: 0,
    retryRequests: 0,
  };

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (request.method() === 'GET' && pathname === '/api/v1/runtime/preflight') {
      return json(route, runtimePayload());
    }

    if (request.method() === 'GET' && pathname === '/api/v1/local-data/summary') {
      metrics.localDataRequests += 1;
      return json(route, localDataPayload());
    }

    if (request.method() === 'GET' && pathname === '/api/v1/transcriptions') {
      metrics.listRequests += 1;
      return json(route, {
        jobs: metrics.uploadRequests > 0 ? [historyPayload(terminalStatus)] : [],
        limit: 20,
      });
    }

    if (request.method() === 'POST' && pathname === '/api/v1/transcriptions') {
      metrics.uploadRequests += 1;
      return json(route, {
        job_id: JOB_ID,
        status: 'queued',
        status_url: `/api/v1/transcriptions/${JOB_ID}/status`,
        result_url: `/api/v1/transcriptions/${JOB_ID}`,
        created_at: createdAt,
      });
    }

    if (request.method() === 'POST' && pathname === `/api/v1/transcriptions/${JOB_ID}/retry`) {
      metrics.retryRequests += 1;
      return json(route, {
        job_id: `${JOB_ID}-retry`,
        status: 'queued',
        status_url: `/api/v1/transcriptions/${JOB_ID}-retry/status`,
        result_url: `/api/v1/transcriptions/${JOB_ID}-retry`,
        created_at: createdAt,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}-retry/status`) {
      return json(route, {
        job_id: `${JOB_ID}-retry`,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        message: '任務已重新排入本機分析佇列。',
        error: null,
        created_at: createdAt,
        queued_at: createdAt,
        started_at: null,
        completed_at: null,
        failed_at: null,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}/status`) {
      metrics.statusRequests += 1;
      if (metrics.statusRequests === 1) {
        return json(route, {
          job_id: JOB_ID,
          status: 'processing',
          stage: 'drum_transcription',
          progress: 45,
          message: '正在轉寫鼓 MIDI。',
          error: null,
          created_at: createdAt,
          queued_at: createdAt,
          started_at: createdAt,
          completed_at: null,
          failed_at: null,
        });
      }
      return json(route, {
        job_id: JOB_ID,
        status: terminalStatus,
        stage: 'failed',
        progress: 45,
        message: terminalStatus === 'interrupted' ? '分析中斷，請重新執行任務。' : '分析失敗，請查看錯誤訊息。',
        error: {
          code: 'PIPELINE_FAILED',
          message: '音訊分析流程失敗，請稍後再試或重新上傳音檔。',
          stage: 'drum_transcription',
          retriable: true,
        },
        created_at: createdAt,
        queued_at: createdAt,
        started_at: createdAt,
        completed_at: null,
        failed_at: failedAt,
      });
    }

    if (request.method() === 'GET' && pathname === `/api/v1/transcriptions/${JOB_ID}`) {
      metrics.resultRequests += 1;
    }

    return json(route, { error: { code: 'NOT_MOCKED', message: `Unmocked e2e request: ${pathname}` } }, 404);
  });

  return metrics;
}

function runtimePayload() {
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
        next_steps: ['設定 verification input 後再執行 true-AI opt-in smoke。'],
      },
      musescore_pdf: { ready: false },
    },
    smoke_commands: {},
    checked_at: checkedAt,
    error: null,
  };
}

function localDataPayload() {
  return {
    schema_version: '1.0',
    status: 'dry_run',
    dry_run: true,
    execute_supported: false,
    storage_root_name: 'storage',
    job_dir_count: 1,
    database_status: 'readable',
    database_job_count: 1,
    orphan_job_dir_count: 0,
    warnings: [],
  };
}

function historyPayload(status: 'completed' | 'failed' | 'interrupted') {
  return {
    job_id: JOB_ID,
    title: status === 'completed' ? 'Browser Smoke' : `Browser Smoke ${status}`,
    file_name: 'synthetic_clean_drum_pattern.wav',
    status,
    stage: status === 'completed' ? 'completed' : 'failed',
    progress: status === 'completed' ? 100 : 45,
    created_at: createdAt,
    completed_at: status === 'completed' ? completedAt : null,
    failed_at: status === 'completed' ? null : failedAt,
    exports:
      status === 'completed'
        ? {
            midi: 'available',
            musicxml: 'available',
            pdf: 'failed',
          }
        : {},
    error:
      status === 'completed'
        ? null
        : {
            code: 'PIPELINE_FAILED',
            message: '音訊分析流程失敗，請稍後再試或重新上傳音檔。',
            stage: 'drum_transcription',
            retriable: true,
          },
  };
}

function resultPayload(options: { candidateAnalysis?: boolean } = {}) {
  const timeline = practiceTimeline(options.candidateAnalysis);
  const payload = {
    job_id: JOB_ID,
    status: 'completed',
    stage: 'completed',
    title: 'Browser Smoke',
    created_at: createdAt,
    completed_at: completedAt,
    audio: {
      id: 'audio-browser-smoke',
      file_name: 'synthetic_clean_drum_pattern.wav',
      content_type: 'audio/wav',
      file_size_bytes: 2048,
      duration_seconds: 12,
      sample_rate: 44100,
      channels: 2,
    },
    drum_track: {
      id: 'track-browser-smoke',
      estimated_bpm: 120,
      time_signature: '4/4',
      event_count: 4,
      confidence_label: 'medium',
      warnings: [],
    },
    preview: {
      musicxml_url: null,
    },
    review_timeline: timeline,
    exports: [
      {
        type: 'midi',
        status: 'available',
        content_type: 'audio/midi',
        file_size_bytes: 128,
        checksum: 'midi-checksum',
        download_url: `/api/v1/transcriptions/${JOB_ID}/download/midi`,
      },
      {
        type: 'musicxml',
        status: 'available',
        content_type: 'application/vnd.recordare.musicxml+xml',
        file_size_bytes: 256,
        checksum: 'musicxml-checksum',
        download_url: `/api/v1/transcriptions/${JOB_ID}/download/musicxml`,
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
          warnings: [],
        },
      ],
      artifacts: [
        { type: 'midi', available: true, file_size_bytes: 128, status: 'available' },
        { type: 'musicxml', available: true, file_size_bytes: 256, status: 'available' },
        { type: 'pdf', available: false, file_size_bytes: null, status: 'failed' },
      ],
      warnings: ['mock_ai_enabled'],
      quality: {
        raw_event_count: 4,
        processed_event_count: 4,
        raw_note_histogram: { '36': 1, '38': 2, '42': 1 },
        processed_drum_counts: { closed_hat: 1, kick: 1, snare: 2 },
        duration_seconds: 12,
        tempo_bpm: 120,
        estimated_measure_count: 1,
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
  };
  if (options.candidateAnalysis) {
    payload.pipeline.mode = 'true_ai';
    payload.pipeline.candidate_analysis = {
      schema_version: '1.0',
      status: 'completed',
      recommended_candidate_id: 'threshold_0_4',
      candidates: [
        candidatePayload('threshold_0_4', 1, 0.4, 'recommended_for_practice', 82, timeline, payload.pipeline.quality, payload.pipeline.validation),
        candidatePayload('threshold_0_5', 2, 0.5, 'reference_with_caveats', 58, timeline, payload.pipeline.quality, payload.pipeline.validation),
      ],
    };
  }
  return payload;
}

function practiceTimeline(includeAccompaniment = false) {
  return {
    schema_version: '1.0',
    timing_source: 'score_tempo',
    tempo_bpm: 120,
    audio_sources: [
      { kind: 'original', label: '原始音訊', available: true, playback_url: `/api/v1/transcriptions/${JOB_ID}/review-audio/original` },
      { kind: 'drums_stem', label: '分離鼓聲', available: true, playback_url: `/api/v1/transcriptions/${JOB_ID}/review-audio/drums_stem` },
      ...(includeAccompaniment ? [{ kind: 'accompaniment', label: '去鼓後伴奏', available: true, playback_url: `/api/v1/transcriptions/${JOB_ID}/review-audio/accompaniment` }] : []),
    ],
    measures: [{ measure_index: 1, start_seconds: 0, end_seconds: 2, render_kind: 'groove', drum_counts: { kick: 1, snare: 1 }, warnings: [] }],
    performance_playback: { available: true, event_count: 2, events: [{ time_seconds: 0, drum: 'kick', velocity: 100 }, { time_seconds: 0.5, drum: 'snare', velocity: 100 }] },
  };
}

function candidatePayload(
  candidateId: string,
  rank: number,
  threshold: number,
  recommendation: 'recommended_for_practice' | 'reference_with_caveats',
  score: number,
  timeline: ReturnType<typeof practiceTimeline>,
  quality: object,
  validation: object,
) {
  return {
    candidate_id: candidateId,
    rank,
    position: rank,
    status: 'completed',
    selected: rank === 1,
    config: { threshold, adtof_threshold_preset: 'separated_v1', tom_filter_preset: 'tom_guard_v1' },
    recommendation: {
      score,
      recommendation,
      reasons: recommendation === 'recommended_for_practice' ? ['節奏與譜面結構相對穩定'] : ['可用於跟練，但部分細節可能不準'],
      rejected: false,
    },
    preview: { musicxml_url: `/api/v1/transcriptions/${JOB_ID}/candidates/${candidateId}/download/musicxml` },
    exports: [
      { type: 'midi', status: 'available', download_url: `/api/v1/transcriptions/${JOB_ID}/candidates/${candidateId}/download/midi` },
      { type: 'musicxml', status: 'available', download_url: `/api/v1/transcriptions/${JOB_ID}/candidates/${candidateId}/download/musicxml` },
      { type: 'pdf', status: 'failed', download_url: null },
    ],
    quality,
    validation,
    review_timeline: timeline,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function expectPublicSafe(page: Page) {
  const bodyText = await page.locator('body').innerText();
  for (const unsafePath of ['/Users/', '/tmp/', '/private/tmp/', '/var/folders/']) {
    expect(bodyText).not.toContain(unsafePath);
  }
  const normalizedBodyText = bodyText.toLowerCase();
  for (const unsafeDiagnostic of [
    'traceback',
    'stdout',
    'stderr',
    'raw command',
    'command_template',
  ]) {
    expect(normalizedBodyText).not.toContain(unsafeDiagnostic);
  }
}

import { expect, test, type Page, type Route } from '@playwright/test';
import path from 'node:path';

const JOB_ID = 'job-browser-smoke';
const checkedAt = '2026-07-03T00:00:00Z';
const createdAt = '2026-07-03T00:00:05Z';
const completedAt = '2026-07-03T00:00:07Z';

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
  await expect(page.getByText('分析完成。')).toBeVisible();
  await expect(page.getByText('MusicXML preview', { exact: true })).toBeVisible();
  await expect(page.getByText('MusicXML preview unavailable')).toBeVisible();
  await expect(page.getByText('MusicXML validation')).toBeVisible();
  await expect(page.getByText('PDF validation')).toBeVisible();
  await expect(page.getByText('optional unavailable').first()).toBeVisible();

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

  expect(apiMetrics.uploadRequests).toBe(1);
  expect(apiMetrics.statusRequests).toBeGreaterThanOrEqual(2);
  expect(apiMetrics.resultRequests).toBe(1);
});

interface MockApiMetrics {
  uploadRequests: number;
  statusRequests: number;
  resultRequests: number;
}

async function installMockApi(page: Page): Promise<MockApiMetrics> {
  const metrics: MockApiMetrics = {
    uploadRequests: 0,
    statusRequests: 0,
    resultRequests: 0,
  };

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (request.method() === 'GET' && pathname === '/api/v1/runtime/preflight') {
      return json(route, {
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
      return json(route, resultPayload());
    }

    return json(route, { error: { code: 'NOT_MOCKED', message: `Unmocked e2e request: ${pathname}` } }, 404);
  });

  return metrics;
}

function resultPayload() {
  return {
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
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

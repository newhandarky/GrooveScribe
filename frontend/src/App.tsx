import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  ApiError,
  downloadUrl,
  getRuntimePreflight,
  getTranscriptionResult,
  getTranscriptionStatus,
  uploadTranscription,
} from './services/api';
import type {
  JobStatusResponse,
  RuntimePreflightResponse,
  TranscriptionResultResponse,
} from './services/types';
import {
  formatDateTime,
  isTerminalJobStatus,
  runtimeStatusTone,
  stageLabel,
} from './services/viewModel';

const POLL_INTERVAL_MS = 1500;
const ACTIVE_JOB_STORAGE_KEY = 'groovescribe.activeJobId';

export function App() {
  const [runtime, setRuntime] = useState<RuntimePreflightResponse | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [uploading, setUploading] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    const urlJobId = new URLSearchParams(window.location.search).get('jobId')?.trim();
    return urlJobId || window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
  });
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [result, setResult] = useState<TranscriptionResultResponse | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  const refreshRuntime = async () => {
    setRuntimeLoading(true);
    setRuntimeError(null);
    try {
      setRuntime(await getRuntimePreflight());
    } catch (error) {
      setRuntime(null);
      setRuntimeError(messageFromError(error));
    } finally {
      setRuntimeLoading(false);
    }
  };

  useEffect(() => {
    void refreshRuntime();
  }, []);

  useEffect(() => {
    if (!activeJobId) {
      setJobStatus(null);
      setResult(null);
      setJobError(null);
      return;
    }
    window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, activeJobId);
    void refreshJob(activeJobId);
    return () => {
      if (pollTimer.current) {
        window.clearTimeout(pollTimer.current);
      }
    };
  }, [activeJobId]);

  const refreshJob = async (jobId: string) => {
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }
    setJobError(null);
    try {
      const status = await getTranscriptionStatus(jobId);
      setJobStatus(status);
      if (status.status === 'completed') {
        setResult(await getTranscriptionResult(jobId));
        return;
      }
      setResult(null);
      if (!isTerminalJobStatus(status.status)) {
        pollTimer.current = window.setTimeout(() => {
          void refreshJob(jobId);
        }, POLL_INTERVAL_MS);
      }
    } catch (error) {
      setJobError(messageFromError(error));
    }
  };

  const submitUpload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setJobError('請先選擇 MP3 或 WAV 音檔。');
      return;
    }
    setUploading(true);
    setJobError(null);
    setResult(null);
    try {
      const upload = await uploadTranscription({ file: selectedFile, title });
      setActiveJobId(upload.job_id);
      setJobStatus({
        job_id: upload.job_id,
        status: upload.status,
        stage: 'queued',
        progress: 0,
        message: '任務已排入本機分析佇列。',
        error: null,
        created_at: upload.created_at,
      });
      setSelectedFile(null);
      setTitle('');
    } catch (error) {
      setJobError(messageFromError(error));
    } finally {
      setUploading(false);
    }
  };

  const resetJob = () => {
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }
    window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
    setActiveJobId(null);
    setJobStatus(null);
    setResult(null);
    setJobError(null);
  };

  const runtimeTone = runtime ? runtimeStatusTone(runtime.status) : 'neutral';
  const canUpload = runtime?.mock_ai_ready === true && !uploading;

  return (
    <main className="appShell">
      <header className="topBar">
        <div>
          <p className="eyebrow">GrooveScribe Local V1</p>
          <h1>本機鼓譜轉寫工作台</h1>
        </div>
        <div className={`statusPill ${runtimeTone}`}>
          {runtimeLoading ? 'checking' : runtime?.status ?? 'unknown'}
        </div>
      </header>

      <section className="layoutGrid">
        <div className="leftPane">
          <RuntimePanel
            runtime={runtime}
            loading={runtimeLoading}
            error={runtimeError}
            onRefresh={() => void refreshRuntime()}
          />
          <UploadPanel
            canUpload={canUpload}
            uploading={uploading}
            selectedFile={selectedFile}
            title={title}
            runtime={runtime}
            onFileChange={setSelectedFile}
            onTitleChange={setTitle}
            onSubmit={submitUpload}
          />
        </div>

        <JobPanel
          activeJobId={activeJobId}
          status={jobStatus}
          result={result}
          error={jobError}
          onRefresh={() => activeJobId && void refreshJob(activeJobId)}
          onReset={resetJob}
        />
      </section>
    </main>
  );
}

export function RuntimePanel({
  runtime,
  loading,
  error,
  onRefresh,
}: {
  runtime: RuntimePreflightResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const checks = runtime?.checks ?? {};
  const missing = runtime?.missing_requirements ?? [];

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Runtime</p>
          <h2>本機 AI 環境</h2>
        </div>
        <button className="secondaryButton" type="button" onClick={onRefresh} disabled={loading}>
          {loading ? '檢查中' : '重新檢查'}
        </button>
      </div>

      {error ? <div className="alert error">{error}</div> : null}
      {runtime?.error ? <div className="alert error">{runtime.error.message}</div> : null}
      <RuntimeStatusNote runtime={runtime} />

      <div className="runtimeSummary">
        <Metric label="Mock pipeline" value={runtime?.mock_ai_ready ? 'ready' : 'not ready'} />
        <Metric label="True AI" value={runtime?.true_ai_ready ? 'ready' : 'not ready'} />
        <Metric label="Checked" value={runtime ? formatDateTime(runtime.checked_at) : '-'} />
      </div>

      {missing.length ? (
        <div className="alert warn">
          <strong>Missing requirements</strong>
          <ul>
            {missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="checkGrid">
        <RuntimeCheck label="AI Python" value={checks.ai_python} />
        <RuntimeCheck label="ffmpeg" value={checks.ffmpeg} />
        <RuntimeCheck label="Demucs" value={checks.demucs} />
        <RuntimeCheck label="ADTOF" value={checks.adtof} />
        <RuntimeCheck label="PDF" value={checks.musescore_pdf} />
      </div>

      <AdtofDiagnostic value={checks.adtof} />
    </section>
  );
}

function RuntimeStatusNote({ runtime }: { runtime: RuntimePreflightResponse | null }) {
  if (!runtime) {
    return <div className="alert warn">Runtime 尚未完成檢查，完成後才能判斷本機 pipeline 可用範圍。</div>;
  }

  const descriptions: Record<string, string> = {
    ready: 'Mock pipeline 與 true AI runtime 都可用。V1 預設仍可使用 mock-ai smoke 驗證流程。',
    degraded: 'Mock pipeline 可用，true AI runtime 尚未 ready；你仍可用本機 mock-ai flow 上傳與驗證 UI / artifact contract。',
    not_ready: 'Mock pipeline 也尚未 ready；請先修復 runtime 缺口，upload 會維持停用。',
    error: 'Runtime preflight 本身失敗；請先修復 AI Python 或 diagnostics script 執行問題。',
  };

  return <div className={`runtimeNote ${runtimeStatusTone(runtime.status)}`}>{descriptions[runtime.status]}</div>;
}

function AdtofDiagnostic({ value }: { value: unknown }) {
  const check = recordFromUnknown(value);
  if (!Object.keys(check).length) return null;
  const statusCode = stringFromUnknown(check.status_code) ?? 'unknown';
  const summary = stringFromUnknown(check.summary) ?? 'ADTOF runtime 尚未 ready。';
  const nextSteps = stringListFromUnknown(check.next_steps);
  const optionalEnv = stringListFromUnknown(check.optional_env);
  const reason = stringFromUnknown(check.output_verification_reason);

  return (
    <div className="diagnosticBlock">
      <div className="diagnosticHeader">
        <div>
          <span>ADTOF diagnosis</span>
          <strong>{statusCode}</strong>
        </div>
        <span className={check.ready ? 'statusText ready' : 'statusText warn'}>
          {check.ready ? 'ready' : 'needs attention'}
        </span>
      </div>
      <p>{summary}</p>
      {reason ? <p className="diagnosticReason">{reason}</p> : null}
      {nextSteps.length ? (
        <div>
          <strong>Next steps</strong>
          <ul>
            {nextSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {optionalEnv.length ? (
        <p className="diagnosticMeta">Optional env: {optionalEnv.join(', ')}</p>
      ) : null}
    </div>
  );
}

export function UploadPanel({
  canUpload,
  uploading,
  selectedFile,
  title,
  runtime,
  onFileChange,
  onTitleChange,
  onSubmit,
}: {
  canUpload: boolean;
  uploading: boolean;
  selectedFile: File | null;
  title: string;
  runtime: RuntimePreflightResponse | null;
  onFileChange: (file: File | null) => void;
  onTitleChange: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  const blockedReason = useMemo(() => {
    if (!runtime) return 'Runtime 尚未完成檢查。';
    if (!runtime.mock_ai_ready) return 'Mock pipeline 尚未 ready，請先修正 runtime。';
    return null;
  }, [runtime]);

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Upload</p>
          <h2>新增轉寫任務</h2>
        </div>
      </div>
      <form className="uploadForm" onSubmit={onSubmit}>
        <label className="field">
          <span>Title</span>
          <input value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="Demo groove" />
        </label>
        <label className="fileDrop">
          <input
            type="file"
            accept=".mp3,.wav,audio/mpeg,audio/wav,audio/x-wav"
            onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
          />
          <span>{selectedFile ? selectedFile.name : '選擇 MP3 或 WAV 音檔'}</span>
        </label>
        {blockedReason ? <p className="formNote">{blockedReason}</p> : null}
        <button className="primaryButton" type="submit" disabled={!canUpload || !selectedFile}>
          {uploading ? '建立中' : '開始本機分析'}
        </button>
      </form>
    </section>
  );
}

function JobPanel({
  activeJobId,
  status,
  result,
  error,
  onRefresh,
  onReset,
}: {
  activeJobId: string | null;
  status: JobStatusResponse | null;
  result: TranscriptionResultResponse | null;
  error: string | null;
  onRefresh: () => void;
  onReset: () => void;
}) {
  return (
    <section className="panel jobPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Job</p>
          <h2>{activeJobId ? '分析狀態與輸出' : '等待任務'}</h2>
        </div>
        <div className="buttonRow">
          <button className="secondaryButton" type="button" onClick={onRefresh} disabled={!activeJobId}>
            更新
          </button>
          <button className="secondaryButton" type="button" onClick={onReset} disabled={!activeJobId}>
            清除
          </button>
        </div>
      </div>

      {error ? <div className="alert error">{error}</div> : null}

      {!activeJobId ? (
        <div className="emptyState">
          <h3>尚未建立任務</h3>
          <p>上傳音檔後，這裡會顯示 queue、processing、completed 或 failed 狀態。</p>
        </div>
      ) : null}

      {status ? <JobStatusCard status={status} /> : null}
      {result ? <ResultCard result={result} /> : null}
    </section>
  );
}

export function JobStatusCard({ status }: { status: JobStatusResponse }) {
  return (
    <div className="statusCard">
      <div className="statusLine">
        <span className={`statusPill ${status.status}`}>{status.status}</span>
        <span>{stageLabel(status.stage)}</span>
      </div>
      <div className="progressTrack" aria-label={`Progress ${status.progress}%`}>
        <div className="progressFill" style={{ width: `${Math.max(0, Math.min(100, status.progress))}%` }} />
      </div>
      <p>{status.message}</p>
      <dl className="detailList">
        <div>
          <dt>Job ID</dt>
          <dd>{status.job_id}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDateTime(status.created_at)}</dd>
        </div>
        {status.error ? (
          <div>
            <dt>Error</dt>
            <dd>{status.error.message ?? status.error.code}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export function ResultCard({ result }: { result: TranscriptionResultResponse }) {
  const availableExports = result.exports.filter((item) => item.status === 'available');
  const unavailableExports = result.exports.filter((item) => item.status !== 'available');

  return (
    <div className="resultCard">
      <div className="resultHeader">
        <div>
          <h3>{result.title || result.audio.file_name}</h3>
          <p>
            {result.audio.content_type} · {formatBytes(result.audio.file_size_bytes)}
          </p>
        </div>
        {result.drum_track ? (
          <div className="scoreStats">
            <span>{result.drum_track.event_count} events</span>
            <span>{result.drum_track.time_signature}</span>
            <span>{result.drum_track.estimated_bpm ? `${Math.round(result.drum_track.estimated_bpm)} BPM` : 'BPM -'}</span>
          </div>
        ) : null}
      </div>

      {result.drum_track?.warnings.length ? (
        <div className="alert warn">
          <strong>Warnings</strong>
          <ul>
            {result.drum_track.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="downloadGrid">
        {availableExports.map((item) => (
          <a className="downloadButton" href={downloadUrl(item.download_url)} key={item.type}>
            {item.type.toUpperCase()}
            <span>{formatBytes(item.file_size_bytes)}</span>
          </a>
        ))}
      </div>

      {unavailableExports.length ? (
        <div className="exportList">
          {unavailableExports.map((item) => (
            <div className="exportRow" key={item.type}>
              <span>{item.type.toUpperCase()}</span>
              <span>{item.status}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RuntimeCheck({ label, value }: { label: string; value: unknown }) {
  const check = recordFromUnknown(value);
  const ready = Boolean(check.ready ?? check.available);
  return (
    <div className="checkItem">
      <span className={ready ? 'dot ok' : 'dot warn'} />
      <div>
        <strong>{label}</strong>
        <span>{ready ? 'ready' : 'needs attention'}</span>
      </div>
    </div>
  );
}

function recordFromUnknown(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function stringFromUnknown(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function stringListFromUnknown(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function messageFromError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return '發生未預期錯誤。';
}

function formatBytes(value: number | null | undefined): string {
  if (!value) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

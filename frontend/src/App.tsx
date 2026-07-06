import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  ApiError,
  downloadUrl,
  getLocalDataSummary,
  getRuntimePreflight,
  getTranscriptionResult,
  getTranscriptionStatus,
  listTranscriptions,
  retryTranscription,
  uploadTranscription,
} from './services/api';
import type {
  JobStatusResponse,
  LocalDataSummaryResponse,
  RuntimePreflightResponse,
  TranscriptionJobSummary,
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
  const [jobHistory, setJobHistory] = useState<TranscriptionJobSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [localData, setLocalData] = useState<LocalDataSummaryResponse | null>(null);
  const [localDataError, setLocalDataError] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
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

  const refreshJobHistory = async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const response = await listTranscriptions(20);
      setJobHistory(response.jobs);
    } catch (error) {
      setHistoryError(messageFromError(error));
    } finally {
      setHistoryLoading(false);
    }
  };

  const refreshLocalData = async () => {
    setLocalDataError(null);
    try {
      setLocalData(await getLocalDataSummary());
    } catch (error) {
      setLocalData(null);
      setLocalDataError(messageFromError(error));
    }
  };

  useEffect(() => {
    void refreshRuntime();
    void refreshJobHistory();
    void refreshLocalData();
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
        void refreshJobHistory();
        return;
      }
      setResult(null);
      if (!isTerminalJobStatus(status.status)) {
        pollTimer.current = window.setTimeout(() => {
          void refreshJob(jobId);
        }, POLL_INTERVAL_MS);
      } else {
        void refreshJobHistory();
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
      void refreshJobHistory();
    } catch (error) {
      setJobError(messageFromError(error));
    } finally {
      setUploading(false);
    }
  };

  const retryJob = async (jobId: string) => {
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }
    setRetryingJobId(jobId);
    setJobError(null);
    setResult(null);
    try {
      const retry = await retryTranscription(jobId);
      setActiveJobId(retry.job_id);
      setJobStatus({
        job_id: retry.job_id,
        status: retry.status,
        stage: 'queued',
        progress: 0,
        message: '任務已重新排入本機分析佇列。',
        error: null,
        created_at: retry.created_at,
      });
      void refreshJobHistory();
    } catch (error) {
      setJobError(messageFromError(error));
    } finally {
      setRetryingJobId(null);
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
          <LocalDataPanel
            summary={localData}
            error={localDataError}
            onRefresh={() => void refreshLocalData()}
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
          <JobHistoryPanel
            jobs={jobHistory}
            loading={historyLoading}
            error={historyError}
            activeJobId={activeJobId}
            retryingJobId={retryingJobId}
            onRefresh={() => void refreshJobHistory()}
            onSelectJob={setActiveJobId}
            onRetry={(jobId) => void retryJob(jobId)}
          />
        </div>

        <JobPanel
          activeJobId={activeJobId}
          status={jobStatus}
          result={result}
          error={jobError}
          onRefresh={() => activeJobId && void refreshJob(activeJobId)}
          onRetry={(jobId) => void retryJob(jobId)}
          onReset={resetJob}
          retryingJobId={retryingJobId}
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

export function LocalDataPanel({
  summary,
  error,
  onRefresh,
}: {
  summary: LocalDataSummaryResponse | null;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Local data</p>
          <h2>本機資料狀態</h2>
        </div>
        <button className="secondaryButton" type="button" onClick={onRefresh}>
          更新
        </button>
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      {summary ? (
        <div className="localDataGrid">
          <Metric label="Storage root" value={summary.storage_root_name} />
          <Metric label="Job dirs" value={String(summary.job_dir_count)} />
          <Metric label="DB" value={summary.database_status} />
          <Metric label="Orphans" value={String(summary.orphan_job_dir_count)} />
        </div>
      ) : (
        <p className="formNote">尚未取得本機資料摘要。</p>
      )}
      <p className="formNote">
        {summary?.execute_supported === false
          ? '目前只提供 dry-run 可視狀態；reset / cleanup 不會從 UI 刪除資料。'
          : '本機資料摘要僅顯示 public-safe 統計。'}
      </p>
    </section>
  );
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

export function JobHistoryPanel({
  jobs,
  loading,
  error,
  activeJobId,
  retryingJobId,
  onRefresh,
  onSelectJob,
  onRetry,
}: {
  jobs: TranscriptionJobSummary[];
  loading: boolean;
  error: string | null;
  activeJobId: string | null;
  retryingJobId: string | null;
  onRefresh: () => void;
  onSelectJob: (jobId: string) => void;
  onRetry: (jobId: string) => void;
}) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">History</p>
          <h2>近期任務</h2>
        </div>
        <button className="secondaryButton" type="button" onClick={onRefresh} disabled={loading}>
          {loading ? '載入中' : '更新'}
        </button>
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      {!loading && !jobs.length ? <p className="formNote">尚無近期任務。</p> : null}
      {jobs.length ? (
        <div className="historyList">
          {jobs.map((job) => (
            <div className={job.job_id === activeJobId ? 'historyRow active' : 'historyRow'} key={job.job_id}>
              <div className="historyMain">
                <div>
                  <strong>{job.title || job.file_name}</strong>
                  <span>{job.file_name}</span>
                </div>
                <span className={`statusPill ${job.status}`}>{job.status}</span>
              </div>
              <div className="historyMeta">
                <span>{stageLabel(job.stage)}</span>
                <span>{job.progress}%</span>
                <span>{formatDateTime(job.completed_at ?? job.failed_at ?? job.created_at)}</span>
              </div>
              {Object.keys(job.exports).length ? (
                <div className="historyExports">
                  {Object.entries(job.exports).map(([type, status]) => (
                    <span key={`${job.job_id}-${type}`}>
                      {type.toUpperCase()} {status}
                    </span>
                  ))}
                </div>
              ) : null}
              {job.error?.message ? <p className="historyError">{job.error.message}</p> : null}
              <div className="historyActions">
                <button className="secondaryButton" type="button" onClick={() => onSelectJob(job.job_id)}>
                  查看
                </button>
                {canRetryJobStatus(job.status) ? (
                  <button
                    className="secondaryButton"
                    type="button"
                    onClick={() => onRetry(job.job_id)}
                    disabled={retryingJobId === job.job_id}
                  >
                    {job.status === 'completed' ? '重新執行' : retryingJobId === job.job_id ? '重試中' : '重試'}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function JobPanel({
  activeJobId,
  status,
  result,
  error,
  onRefresh,
  onRetry,
  onReset,
  retryingJobId,
}: {
  activeJobId: string | null;
  status: JobStatusResponse | null;
  result: TranscriptionResultResponse | null;
  error: string | null;
  onRefresh: () => void;
  onRetry: (jobId: string) => void;
  onReset: () => void;
  retryingJobId: string | null;
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

      {status ? (
        <JobStatusCard
          status={status}
          onRetry={canRetryJobStatus(status.status) ? onRetry : undefined}
          retrying={retryingJobId === status.job_id}
        />
      ) : null}
      {result ? <ResultCard result={result} onRerun={onRetry} rerunning={retryingJobId === result.job_id} /> : null}
    </section>
  );
}

export function JobStatusCard({
  status,
  onRetry,
  retrying = false,
}: {
  status: JobStatusResponse;
  onRetry?: (jobId: string) => void;
  retrying?: boolean;
}) {
  const guidance =
    status.status === 'interrupted'
      ? '本機服務曾在分析中停止。請重新上傳音檔或保留 artifacts 後再執行新的轉寫。'
      : status.status === 'failed'
        ? '分析失敗時請先查看錯誤 stage；mock flow 可重試，true AI flow 請先回到 runtime diagnostics 修復環境。'
        : null;

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
      {guidance ? <p className="guidanceText">{guidance}</p> : null}
      {onRetry ? (
        <div className="buttonRow">
          <button className="secondaryButton" type="button" onClick={() => onRetry(status.job_id)} disabled={retrying}>
            {status.status === 'completed' ? '重新執行' : retrying ? '重試中' : '重試'}
          </button>
        </div>
      ) : null}
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

export function ResultCard({
  result,
  onRerun,
  rerunning = false,
}: {
  result: TranscriptionResultResponse;
  onRerun?: (jobId: string) => void;
  rerunning?: boolean;
}) {
  const availableExports = result.exports.filter((item) => item.status === 'available');
  const unavailableExports = result.exports.filter((item) => item.status !== 'available');
  const pipelineMode = result.pipeline?.mode ?? 'unknown';
  const validation = result.pipeline?.validation ?? null;

  return (
    <div className="resultCard">
      <div className="resultHeader">
        <div>
          <h3>{result.title || result.audio.file_name}</h3>
          <p>
            {result.audio.content_type} · {formatBytes(result.audio.file_size_bytes)}
          </p>
        </div>
        <div className="resultMetaStack">
          <span className={`pipelineBadge ${pipelineMode === 'true_ai' ? 'trueAi' : pipelineMode}`}>
            {pipelineMode === 'true_ai' ? 'TRUE AI' : pipelineMode.toUpperCase()}
          </span>
          {onRerun ? (
            <button className="secondaryButton compactButton" type="button" onClick={() => onRerun(result.job_id)} disabled={rerunning}>
              {rerunning ? '重新排隊中' : '重新執行'}
            </button>
          ) : null}
          {result.drum_track ? (
            <div className="scoreStats">
              <span>{result.drum_track.event_count} events</span>
              <span>{result.drum_track.time_signature}</span>
              <span>
                {result.drum_track.estimated_bpm ? `${Math.round(result.drum_track.estimated_bpm)} BPM` : 'BPM -'}
              </span>
            </div>
          ) : null}
        </div>
      </div>

      <PipelineReview pipeline={result.pipeline} exports={result.exports} />
      <MusicXmlPreview url={result.preview.musicxml_url} validation={validation} />

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

function MusicXmlPreview({
  url,
  validation,
}: {
  url: string | null;
  validation: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['validation']> | null;
}) {
  const renderTargetRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'unavailable' | 'error'>(
    url ? 'idle' : 'unavailable',
  );

  useEffect(() => {
    if (!url || !renderTargetRef.current) {
      setStatus('unavailable');
      return;
    }
    let canceled = false;
    setStatus('loading');
    renderTargetRef.current.replaceChildren();
    void import('opensheetmusicdisplay')
      .then(async ({ OpenSheetMusicDisplay }) => {
        if (canceled || !renderTargetRef.current) return;
        const osmd = new OpenSheetMusicDisplay(renderTargetRef.current, {
          autoResize: true,
          backend: 'svg',
          drawTitle: false,
        });
        await osmd.load(url);
        if (canceled) return;
        await osmd.render();
        if (!canceled) setStatus('ready');
      })
      .catch(() => {
        if (!canceled) setStatus('error');
      });
    return () => {
      canceled = true;
    };
  }, [url]);

  const musicxml = validation?.musicxml;
  const pdf = validation?.pdf;
  const musicxmlStatus = validation
    ? musicxml?.parseable
      ? 'parseable'
      : musicxml?.available
        ? 'needs review'
        : 'unavailable'
    : 'not reported';
  const pdfStatus = validation
    ? pdf?.available
      ? pdf.openable
        ? 'available'
        : 'needs review'
      : 'optional unavailable'
    : 'not reported';

  return (
    <div className="musicXmlPreview">
      <div className="reviewHeader">
        <strong>MusicXML preview</strong>
        <span>{previewStatusLabel(status)}</span>
      </div>
      <div className="validationGrid">
        <ValidationStatus
          label="MusicXML validation"
          status={musicxmlStatus}
          warnings={musicxml?.warnings ?? []}
        />
        <ValidationStatus
          label="PDF validation"
          status={pdfStatus}
          warnings={pdf?.warnings ?? []}
        />
      </div>
      <div className="musicXmlCanvas">
        <div className="musicXmlRenderTarget" ref={renderTargetRef} />
      </div>
      {status === 'unavailable' ? <p className="previewFallback">MusicXML preview unavailable</p> : null}
      {status === 'loading' || status === 'idle' ? <p className="previewFallback">Loading preview</p> : null}
      {status === 'error' ? (
        <p className="previewFallback">Preview renderer unavailable; download remains available.</p>
      ) : null}
    </div>
  );
}

function ValidationStatus({ label, status, warnings }: { label: string; status: string; warnings: string[] }) {
  return (
    <div className="validationStatus">
      <span>{label}</span>
      <strong>{status}</strong>
      {warnings.length ? (
        <div className="inlineWarnings">
          {warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function previewStatusLabel(status: 'idle' | 'loading' | 'ready' | 'unavailable' | 'error'): string {
  if (status === 'ready') return 'rendered';
  if (status === 'error') return 'fallback';
  if (status === 'unavailable') return 'unavailable';
  return 'loading';
}

function PipelineReview({
  pipeline,
  exports,
}: {
  pipeline: TranscriptionResultResponse['pipeline'];
  exports: TranscriptionResultResponse['exports'];
}) {
  if (!pipeline) return null;
  const stages = pipeline.stages ?? [];
  const warnings = pipeline.warnings ?? [];
  const quality = pipeline.quality;
  const validation = pipeline.validation;

  return (
    <div className="pipelineReview">
      <div className="reviewHeader">
        <strong>Pipeline summary</strong>
        <span>{pipeline.pipeline_log_available ? 'log available' : 'log unavailable'}</span>
      </div>
      {quality ? <QualityReview quality={quality} /> : null}
      {validation ? <ArtifactValidationSummary validation={validation} /> : null}
      {stages.length ? (
        <div className="stageList">
          {stages.map((stage) => (
            <div className="stageRow" key={`${stage.name}-${stage.status}`}>
              <span>{stageLabel(stage.name)}</span>
              <span>{stage.status}</span>
              <span>{stage.runtime_seconds !== null ? `${stage.runtime_seconds.toFixed(2)}s` : '-'}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="exportList compact">
        {exports.map((item) => (
          <div className="exportRow" key={`summary-${item.type}`}>
            <span>{item.type.toUpperCase()}</span>
            <span>
              {item.status}
              {item.type === 'pdf' && item.status !== 'available' ? ' · optional' : ''}
            </span>
          </div>
        ))}
      </div>
      {warnings.length ? (
        <div className="inlineWarnings">
          {warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ArtifactValidationSummary({
  validation,
}: {
  validation: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['validation']>;
}) {
  const pdfStatus = validation.pdf.available ? (validation.pdf.openable ? 'openable' : 'needs review') : 'optional unavailable';
  const musicxmlStatus = validation.musicxml.parseable ? 'parseable' : 'needs review';
  return (
    <div className="artifactValidation">
      <div>
        <span>MusicXML</span>
        <strong>{musicxmlStatus}</strong>
      </div>
      <div>
        <span>PDF</span>
        <strong>{pdfStatus}</strong>
      </div>
    </div>
  );
}

function QualityReview({ quality }: { quality: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['quality']> }) {
  const drumCounts = Object.entries(quality.processed_drum_counts ?? {});
  const flags = quality.quality_flags ?? [];
  const warnings = quality.warnings ?? [];

  return (
    <div className="qualityReview">
      <div className="qualityMetrics">
        <Metric label="Raw events" value={formatNumber(quality.raw_event_count)} />
        <Metric label="Processed events" value={formatNumber(quality.processed_event_count)} />
        <Metric label="Tempo" value={quality.tempo_bpm ? `${Math.round(quality.tempo_bpm)} BPM` : '-'} />
        <Metric label="Measures" value={formatNumber(quality.estimated_measure_count)} />
      </div>
      {drumCounts.length ? (
        <div className="drumCountList">
          {drumCounts.map(([drum, count]) => (
            <span key={drum}>
              {drum}: {count}
            </span>
          ))}
        </div>
      ) : null}
      {flags.length || warnings.length ? (
        <div className="inlineWarnings qualityFlags">
          {[...new Set([...flags, ...warnings])].map((warning) => (
            <span key={warning}>{warning}</span>
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

function canRetryJobStatus(status: string): boolean {
  return status === 'failed' || status === 'interrupted' || status === 'completed';
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

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : String(value);
}

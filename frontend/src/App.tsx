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
  PipelineModeSelection,
  PipelineRunConfigInput,
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
const TRUE_AI_THRESHOLD_PRESET = 'separated_v1';
const TRUE_AI_TOM_FILTER_PRESET = 'tom_guard_v1';
const INITIAL_HISTORY_LIMIT = 5;

export function App() {
  const [runtime, setRuntime] = useState<RuntimePreflightResponse | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [pipelineMode, setPipelineMode] = useState<PipelineModeSelection>('demo_mock');
  const [pipelineModeTouched, setPipelineModeTouched] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    const urlJobId = new URLSearchParams(window.location.search).get('jobId')?.trim();
    return urlJobId || window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
  });
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [result, setResult] = useState<TranscriptionResultResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
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
    if (!runtime || pipelineModeTouched) return;
    setPipelineMode(runtime.true_ai_ready ? 'true_ai' : 'demo_mock');
  }, [pipelineModeTouched, runtime]);

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
      const upload = await uploadTranscription({
        file: selectedFile,
        title,
        ...pipelineConfigInput(pipelineMode),
      });
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

  const retryJob = async (jobId: string, config?: PipelineRunConfigInput) => {
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }
    setRetryingJobId(jobId);
    setJobError(null);
    setResult(null);
    try {
      const retry = await retryTranscription(jobId, config);
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
  const trueAiReady = runtime?.true_ai_ready === true;

  useEffect(() => {
    const analysis = result?.pipeline?.candidate_analysis;
    if (!analysis?.candidates.length) {
      setSelectedCandidateId(null);
      return;
    }
    setSelectedCandidateId((current) =>
      analysis.candidates.some((candidate) => candidate.candidate_id === current)
        ? current
        : analysis.recommended_candidate_id ?? analysis.canonical_candidate_id ?? analysis.candidates[0].candidate_id,
    );
  }, [result]);

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
            pipelineMode={pipelineMode}
            runtime={runtime}
            trueAiReady={trueAiReady}
            onFileChange={setSelectedFile}
            onTitleChange={setTitle}
            onPipelineModeChange={(mode) => {
              setPipelineModeTouched(true);
              setPipelineMode(mode);
            }}
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
          onRetry={(jobId, config) => void retryJob(jobId, config)}
          onReset={resetJob}
          retryingJobId={retryingJobId}
          trueAiReady={trueAiReady}
          selectedCandidateId={selectedCandidateId}
          onCandidateSelect={setSelectedCandidateId}
        />
      </section>
      {result ? <ScorePreviewSection result={result} selectedCandidateId={selectedCandidateId} /> : null}
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

      {error ? (
        <div className="alert error">
          {error}
          <p>若 backend 尚未啟動，請在 repo root 執行 npm run dev:local，或先執行 npm run check:local 檢查本機啟動條件。</p>
        </div>
      ) : null}
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
    ready: 'Mock pipeline 與 true AI runtime 都可用。你可以選 True-AI V1 preset 跑真實音檔；true AI 仍只在明確 opt-in 時執行。',
    degraded: 'Mock pipeline 可用，true AI runtime 尚未 ready。Demo mode 可驗證流程，但不代表真實轉譜品質；true AI smoke 需另行 opt-in。',
    not_ready: 'Mock pipeline 尚未 ready；請先修復 runtime 缺口，upload 會維持停用。',
    error: 'Runtime preflight 本身失敗；請先修復 AI Python 或 diagnostics 執行問題。',
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
          ? '目前只提供 dry-run 可視狀態；reset / cleanup 不會從 UI 刪除 storage 或 DB。'
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
  pipelineMode,
  runtime,
  trueAiReady,
  onFileChange,
  onTitleChange,
  onPipelineModeChange,
  onSubmit,
}: {
  canUpload: boolean;
  uploading: boolean;
  selectedFile: File | null;
  title: string;
  pipelineMode: PipelineModeSelection;
  runtime: RuntimePreflightResponse | null;
  trueAiReady: boolean;
  onFileChange: (file: File | null) => void;
  onTitleChange: (value: string) => void;
  onPipelineModeChange: (value: PipelineModeSelection) => void;
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
        <fieldset className="modeSelector">
          <legend>分析模式</legend>
          <label className={pipelineMode === 'demo_mock' ? 'modeOption active' : 'modeOption'}>
            <input
              type="radio"
              name="pipeline_mode"
              checked={pipelineMode === 'demo_mock'}
              onChange={() => onPipelineModeChange('demo_mock')}
            />
            <span>
              <strong>Demo mode</strong>
              <small>使用 mock pipeline，適合 runtime degraded 或產品流程展示。</small>
            </span>
          </label>
          <label className={pipelineMode === 'true_ai' ? 'modeOption active' : 'modeOption'}>
            <input
              type="radio"
              name="pipeline_mode"
              checked={pipelineMode === 'true_ai'}
              disabled={!trueAiReady}
              onChange={() => onPipelineModeChange('true_ai')}
            />
            <span>
              <strong>True-AI V1 preset</strong>
              <small>套用 separated_v1 + tom_guard_v1，產出 MIDI / MusicXML 與品質報告。</small>
            </span>
          </label>
        </fieldset>
        {!trueAiReady ? <p className="formNote">True-AI runtime 尚未 ready；Demo mode 仍可用。</p> : null}
        {pipelineMode === 'true_ai' ? (
          <div className="presetSummary">
            <span>Preset</span>
            <strong>{TRUE_AI_THRESHOLD_PRESET}</strong>
            <span>Filter</span>
            <strong>{TRUE_AI_TOM_FILTER_PRESET}</strong>
          </div>
        ) : null}
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
  const [visibleCount, setVisibleCount] = useState(INITIAL_HISTORY_LIMIT);
  const initialVisibleJobs = jobs.slice(0, visibleCount);
  const activeHiddenJob = activeJobId
    ? jobs.find((job, index) => job.job_id === activeJobId && index >= visibleCount)
    : undefined;
  const visibleJobs = activeHiddenJob ? [...initialVisibleJobs, activeHiddenJob] : initialVisibleJobs;
  const visibleJobIds = new Set(visibleJobs.map((job) => job.job_id));
  const remainingCount = jobs.filter((job) => !visibleJobIds.has(job.job_id)).length;

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
          {visibleJobs.map((job) => (
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
                <span>{pipelineModeLabel(job.pipeline_config?.mode ?? 'unknown')}</span>
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
          {remainingCount ? (
            <button
              className="secondaryButton historyLoadMoreButton"
              type="button"
              onClick={() => setVisibleCount((count) => Math.min(count + INITIAL_HISTORY_LIMIT, jobs.length))}
            >
              讀取更多
              <span>尚有 {remainingCount} 筆</span>
            </button>
          ) : null}
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
  trueAiReady,
  selectedCandidateId,
  onCandidateSelect,
}: {
  activeJobId: string | null;
  status: JobStatusResponse | null;
  result: TranscriptionResultResponse | null;
  error: string | null;
  onRefresh: () => void;
  onRetry: (jobId: string, config?: PipelineRunConfigInput) => void;
  onReset: () => void;
  retryingJobId: string | null;
  trueAiReady: boolean;
  selectedCandidateId: string | null;
  onCandidateSelect: (candidateId: string | null) => void;
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
          onRetry={canRetryJobStatus(status.status) ? (jobId) => onRetry(jobId) : undefined}
          retrying={retryingJobId === status.job_id}
        />
      ) : null}
      {result ? (
        <ResultCard
          result={result}
          onRerun={onRetry}
          rerunning={retryingJobId === result.job_id}
          trueAiReady={trueAiReady}
          selectedCandidateId={selectedCandidateId}
          onCandidateSelect={onCandidateSelect}
        />
      ) : null}
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
      ? '本機服務曾在分析中停止。你可以保留舊 artifacts，直接重試建立新的本機轉寫任務。'
      : status.status === 'failed'
        ? '分析失敗時可先重試；若是 true AI opt-in 失敗，請回到 Runtime diagnostics 修復環境後再跑 true AI。'
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
  trueAiReady = false,
  selectedCandidateId = null,
  onCandidateSelect,
}: {
  result: TranscriptionResultResponse;
  onRerun?: (jobId: string, config?: PipelineRunConfigInput) => void;
  rerunning?: boolean;
  trueAiReady?: boolean;
  selectedCandidateId?: string | null;
  onCandidateSelect?: (candidateId: string | null) => void;
}) {
  const availableExports = result.exports.filter((item) => item.status === 'available');
  const unavailableExports = result.exports.filter((item) => item.status !== 'available');
  const pipelineMode = result.pipeline?.mode ?? 'unknown';
  const delivery = result.pipeline?.quality?.performance_gate;
  // Legacy and demo results predate the performance gate. Keep their existing
  // download behavior; only an explicit unsafe gate state moves exports into
  // diagnostics.
  const verifiedPerformanceScore = isVerifiedPerformanceScore(delivery);
  const deliverableScore = !delivery || verifiedPerformanceScore || delivery.verdict === 'playable_but_low_confidence';
  const scoreExports = deliverableScore ? availableExports : [];
  const diagnosticExports = deliverableScore ? [] : availableExports;
  const candidateAnalysis = result.pipeline?.candidate_analysis;
  const selectedCandidate = candidateAnalysis?.candidates.find((item) => item.candidate_id === selectedCandidateId)
    ?? candidateAnalysis?.candidates.find((item) => item.candidate_id === candidateAnalysis.recommended_candidate_id)
    ?? candidateAnalysis?.candidates.find((item) => item.candidate_id === candidateAnalysis.canonical_candidate_id)
    ?? candidateAnalysis?.candidates.find((item) => item.selected)
    ?? null;

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
            <div className="rerunActions">
              <button className="secondaryButton compactButton" type="button" onClick={() => onRerun(result.job_id)} disabled={rerunning}>
                {rerunning ? '重新排隊中' : '沿用設定重跑'}
              </button>
              <button
                className="secondaryButton compactButton"
                type="button"
                onClick={() => onRerun(result.job_id, pipelineConfigInput('true_ai'))}
                disabled={rerunning || !trueAiReady}
              >
                True-AI V1
              </button>
              {pipelineMode === 'true_ai' ? (
                <button
                  className="secondaryButton compactButton"
                  type="button"
                  onClick={() => onRerun(result.job_id, pipelineConfigInput('demo_mock'))}
                  disabled={rerunning}
                >
                  Demo mode
                </button>
              ) : null}
            </div>
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

      <PipelineConfigPanel pipeline={result.pipeline} sourceJobId={result.source_job_id} />
      {candidateAnalysis ? (
        <CandidateAnalysisPanel
          analysis={candidateAnalysis}
          selectedCandidate={selectedCandidate}
          onSelect={onCandidateSelect}
        />
      ) : null}
      <SourceComparisonPanel summary={result.source_result_summary} currentPipeline={result.pipeline} />
      <PipelineReview pipeline={result.pipeline} exports={result.exports} />
      <ResultModeGuidance pipeline={result.pipeline} />
      <ReviewPacketPanel result={result} />
      <QualityStatusPanel pipeline={result.pipeline} />
      <PerformanceDeliveryPanel pipeline={result.pipeline} />
      <PracticePlaybackPanel
        key={selectedCandidate?.candidate_id ?? 'canonical'}
        timeline={selectedCandidate?.review_timeline ?? result.review_timeline}
      />

      {result.drum_track?.warnings.length ? (
        <div className="alert warn">
          <strong>Warnings / quality notes</strong>
          <ul>
            {result.drum_track.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {scoreExports.length ? (
        <div className="downloadGrid">
          {scoreExports.map((item) => (
          <a className="downloadButton" href={downloadUrl(item.download_url)} key={item.type}>
              {performanceExportLabel(item.type, verifiedPerformanceScore)}
              <span>{delivery?.verdict === 'playable_but_low_confidence' ? '可播放草稿，未完成對照驗證' : formatBytes(item.file_size_bytes)}</span>
          </a>
          ))}
        </div>
      ) : null}

      {diagnosticExports.length ? (
        <div className="exportList">
          <strong>技術診斷 artifacts</strong>
          <p className="qualityStatusNote">系統未將此結果標示為完成 performance score；可從自動交付包取得技術 artifacts。</p>
          {diagnosticExports.map((item) => (
            <div className="exportRow" key={`diagnostic-${item.type}`}>
              <span>{item.type.toUpperCase()}</span>
              <span>已保留於交付包</span>
            </div>
          ))}
        </div>
      ) : null}

      {unavailableExports.length ? (
        <div className="exportList">
          {unavailableExports.map((item) => (
            <div className="exportRow" key={item.type}>
              <span>{item.type.toUpperCase()}</span>
              <span>{item.type === 'pdf' ? `${item.status} · optional` : item.status}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ScorePreviewSection({
  result,
  selectedCandidateId = null,
}: {
  result: TranscriptionResultResponse;
  selectedCandidateId?: string | null;
}) {
  const candidateAnalysis = result.pipeline?.candidate_analysis;
  const candidate = candidateAnalysis?.candidates.find((item) => item.candidate_id === selectedCandidateId)
    ?? candidateAnalysis?.candidates.find((item) => item.candidate_id === candidateAnalysis.recommended_candidate_id)
    ?? candidateAnalysis?.candidates.find((item) => item.candidate_id === candidateAnalysis.canonical_candidate_id)
    ?? candidateAnalysis?.candidates.find((item) => item.selected)
    ?? null;
  return (
    <section className="panel scorePreviewPanel" aria-label="鼓譜預覽">
      <div className="panelHeader scorePreviewHeader">
        <div>
          <p className="eyebrow">Score preview</p>
          <h2>鼓譜滿版預覽</h2>
        </div>
        <span className="scorePreviewMeta">
          {candidate ? `候選 ${candidate.rank ?? candidate.position ?? '-'} · ${practiceRecommendationLabel(candidate.recommendation.recommendation)}` : result.title || result.audio.file_name}
        </span>
      </div>
      <MusicXmlPreview
        url={candidate?.preview.musicxml_url ?? result.preview.musicxml_url}
        validation={candidate?.validation ?? result.pipeline?.validation ?? null}
        fullWidth
      />
    </section>
  );
}

function CandidateAnalysisPanel({
  analysis,
  selectedCandidate,
  onSelect,
}: {
  analysis: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['candidate_analysis']>;
  selectedCandidate: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['candidate_analysis']>['candidates'][number] | null;
  onSelect?: (candidateId: string | null) => void;
}) {
  const recommendation = selectedCandidate?.recommendation.recommendation ?? 'reanalyze_recommended';
  return (
    <section className={`candidateAnalysisPanel ${recommendation}`}>
      <div className="qualityStatusHeader">
        <div>
          <strong>{practiceRecommendationLabel(recommendation)}</strong>
          <span>系統已比較 {analysis.candidates.length} 組設定，預設選擇較適合跟練的版本。</span>
        </div>
        {selectedCandidate?.recommendation.score !== null && selectedCandidate?.recommendation.score !== undefined ? (
          <span className="qualityScore">{selectedCandidate.recommendation.score}/100</span>
        ) : null}
      </div>
      <div className="candidateButtons" role="list" aria-label="候選版本">
        {analysis.candidates.map((candidate) => (
          <button
            className={candidate.candidate_id === selectedCandidate?.candidate_id ? 'candidateButton selected' : 'candidateButton'}
            type="button"
            key={candidate.candidate_id}
            onClick={() => onSelect?.(candidate.candidate_id)}
            disabled={candidate.status !== 'completed'}
          >
            <span>版本 {candidate.rank ?? candidate.position ?? '-'}</span>
            <strong>{practiceRecommendationLabel(candidate.recommendation.recommendation)}</strong>
            <small>{candidate.config.threshold !== null ? `靈敏度 ${candidate.config.threshold}` : candidate.status}</small>
          </button>
        ))}
      </div>
      {selectedCandidate ? (
        <>
          <ul className="candidateReasons">
            {selectedCandidate.recommendation.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          <details className="candidateDiagnostics">
            <summary>技術診斷</summary>
            <p>事件數：{selectedCandidate.quality?.processed_event_count ?? '-'}；MusicXML：{selectedCandidate.validation?.musicxml?.parseable ? '可讀取' : '需檢查'}</p>
            {selectedCandidate.quality?.quality_flags?.length ? <p>品質旗標：{selectedCandidate.quality.quality_flags.join('、')}</p> : <p>未回報明確品質旗標。</p>}
          </details>
          <div className="downloadGrid compactDownloads">
            {selectedCandidate.exports.filter((item) => item.status === 'available' && item.download_url).map((item) => (
              <a className="downloadButton" href={downloadUrl(item.download_url)} key={item.type}>
                {item.type.toUpperCase()}<span>此候選版本</span>
              </a>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function practiceRecommendationLabel(value: string): string {
  if (value === 'recommended_for_practice') return '推薦用於練習';
  if (value === 'reference_with_caveats') return '可作為參考，細節可能不準';
  return '不建議使用，建議重新分析';
}

function ResultModeGuidance({ pipeline }: { pipeline: TranscriptionResultResponse['pipeline'] }) {
  const mode = pipeline?.mode ?? pipeline?.config?.mode ?? 'unknown';
  const verdict = pipeline?.quality?.quality_verdict;
  const gate = verdict?.candidate_gate;
  const limitations = verdict?.limitations ?? [];
  const performance = pipeline?.quality?.performance_gate;
  const lowQuality =
    gate?.status === 'failed'
    || performance?.verdict === 'needs_better_source'
    || performance?.verdict === 'not_ready'
    || limitations.length > 0
    || verdict?.verdict === 'unknown'
    || (typeof verdict?.usability_score === 'number' && verdict.usability_score < 4);

  if ((mode === 'demo_mock' || mode === 'mock') && lowQuality) {
    return (
      <div className="alert warn">
        <strong>Demo/mock 結果僅供流程驗證</strong>
        <p>這個結果可用來檢查 upload、result review、MIDI / MusicXML 下載與 review packet，但不代表真實音檔轉譜品質。</p>
      </div>
    );
  }

  if (mode !== 'true_ai' || !lowQuality) return null;
  const blockers = limitations.length
    ? limitations.slice(0, 3)
    : performance?.blocking_issues?.slice(0, 3) ?? [];

  return (
    <div className="alert warn">
      <strong>True-AI 結果需要人工修譜或重新嘗試</strong>
      {blockers.length ? <p>主要 blocker：{blockers.map(qualityLimitationLabel).join('、')}</p> : null}
      <ul>
        <li>改用更乾淨的鼓聲來源或分離後 drums stem。</li>
        <li>執行 real audio pilot / quality matrix，比較 threshold 0.3、0.4、0.5、0.6。</li>
        <li>匯出 review packet 給人工修譜，不要把低分草稿當成可直接交付成品。</li>
      </ul>
    </div>
  );
}

type QualityVerdict = NonNullable<NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['quality']>['quality_verdict']>;

function PipelineConfigPanel({
  pipeline,
  sourceJobId,
}: {
  pipeline: TranscriptionResultResponse['pipeline'];
  sourceJobId: string | null;
}) {
  const config = pipeline?.config;
  if (!config && !sourceJobId) return null;
  const mode = config?.mode ?? pipeline?.mode ?? 'unknown';
  return (
    <div className="pipelineConfigPanel">
      <div className="pipelineConfigHeader">
        <strong>Pipeline config</strong>
        <span>per-job settings</span>
      </div>
      <div>
        <span>Mode</span>
        <strong>{pipelineModeLabel(mode)}</strong>
      </div>
      <div>
        <span>ADTOF preset</span>
        <strong>{config?.adtof_threshold_preset ?? '-'}</strong>
      </div>
      <div>
        <span>Postprocess filter</span>
        <strong>{config?.tom_filter_preset ?? '-'}</strong>
      </div>
      {sourceJobId ? (
        <div>
          <span>Source job</span>
          <strong>{sourceJobId}</strong>
        </div>
      ) : null}
    </div>
  );
}

function SourceComparisonPanel({
  summary,
  currentPipeline,
}: {
  summary: TranscriptionResultResponse['source_result_summary'];
  currentPipeline: TranscriptionResultResponse['pipeline'];
}) {
  if (!summary) return null;
  const currentVerdict = currentPipeline?.quality?.quality_verdict;
  const currentCounts = currentPipeline?.quality?.processed_drum_counts ?? {};
  const sourceVerdict = summary.quality_verdict;
  const sourceCounts = summary.processed_drum_counts ?? {};
  return (
    <div className="sourceComparisonPanel">
      <div className="reviewHeader">
        <strong>與前一次比較</strong>
        <span>{summary.job_id}</span>
      </div>
      <div className="comparisonGrid">
        <Metric label="Previous verdict" value={sourceVerdict?.verdict ? qualityVerdictLabel(sourceVerdict.verdict) : 'unknown'} />
        <Metric label="Current verdict" value={currentVerdict?.verdict ? qualityVerdictLabel(currentVerdict.verdict) : 'unknown'} />
        <Metric label="Previous tom" value={formatNumber(sourceCounts.tom)} />
        <Metric label="Current tom" value={formatNumber(currentCounts.tom)} />
        <Metric label="Previous MusicXML" value={summary.musicxml_parseable === true ? '可讀取' : '需檢查'} />
        <Metric label="Current MusicXML" value={currentVerdict?.musicxml_parseable ? '可讀取' : '需檢查'} />
      </div>
    </div>
  );
}

function QualityStatusPanel({ pipeline }: { pipeline: TranscriptionResultResponse['pipeline'] }) {
  const verdict = pipeline?.quality?.quality_verdict ?? unknownQualityVerdict(pipeline?.validation ?? null);
  const gate = verdict.candidate_gate;
  const limitations = verdict.limitations ?? [];
  const tomFilter = pipeline?.quality?.postprocess_filters?.tom_false_positive ?? null;
  const tomFilterLabel = tomFilter ? qualityTomFilterLabel(String(tomFilter.status ?? 'unknown')) : null;
  const notationReadability = pipeline?.quality?.notation_readability ?? {};
  const notationChart = pipeline?.quality?.notation_chart ?? {};
  const suggestions = qualitySuggestionList(limitations, verdict.musicxml_parseable, notationReadability, notationChart);
  const notationLabel = notationReadabilityLabel(notationReadability);
  const chartLabel = notationChartLabel(notationChart);
  const tone = qualityVerdictTone(verdict.verdict);

  return (
    <div className={`qualityStatusPanel ${tone}`}>
      <div className="qualityStatusHeader">
        <div>
          <strong>{qualityVerdictLabel(verdict.verdict)}</strong>
          <span>鼓譜草稿品質</span>
        </div>
        <span className={`qualityScore ${tone}`}>
          {verdict.usability_score !== null ? `${verdict.usability_score}/5` : '未評分'}
        </span>
      </div>
      <div className="qualityStatusGrid">
        <Metric label="Candidate gate" value={gate.status === 'passed' ? 'passed' : gate.status || 'unknown'} />
        <Metric label="MusicXML" value={verdict.musicxml_parseable ? '可讀取' : verdict.musicxml_available ? '需檢查' : '未提供'} />
        <Metric label="譜面可讀性" value={notationLabel} />
        <Metric label="譜面模式" value={chartLabel} />
      </div>
      {notationChart.mode === 'readable_drum_chart_v3' ? (
        <div className="qualityChartStats">
          <span>每小節實寫簡化鼓譜</span>
          <span>完整 core groove：{formatNumber(notationChart.complete_core_groove_measure_count)}</span>
          <span>Hi-hat 小節：{formatNumber(notationChart.hihat_rendered_measure_count)}</span>
          <span>Hi-hat 八分 / 四分：{formatNumber(notationChart.hihat_eighth_pulse_measure_count)} / {formatNumber(notationChart.hihat_quarter_pulse_measure_count)}</span>
          <span>Fill：{formatNumber(notationChart.fill_measure_count)}</span>
          <span>Groove 八分音符：{formatNumber(notationChart.groove_eighth_note_count)}</span>
          <span>Fill 十六分音符：{formatNumber(notationChart.fill_sixteenth_note_count)}</span>
          <span>核心節奏不完整小節：{formatNumber(notationChart.incomplete_core_groove_measure_count)}</span>
        </div>
      ) : null}
      {limitations.length ? (
        <div className="limitationList">
          {limitations.map((limitation) => (
            <span key={limitation}>{qualityLimitationLabel(limitation)}</span>
          ))}
        </div>
      ) : (
        <p className="qualityStatusNote">未回報明確限制。</p>
      )}
      {tomFilterLabel ? (
        <div className="qualityFilterStatus">
          <span>Tom filter</span>
          <strong>{tomFilterLabel}</strong>
        </div>
      ) : null}
      {suggestions.length ? (
        <div className="qualitySuggestions">
          <strong>修譜建議</strong>
          <ul>
            {suggestions.map((suggestion) => (
              <li key={suggestion}>{suggestion}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function PerformanceDeliveryPanel({ pipeline }: { pipeline: TranscriptionResultResponse['pipeline'] }) {
  const gate = pipeline?.quality?.performance_gate;
  if (!gate) return null;
  const verifiedPerformanceScore = isVerifiedPerformanceScore(gate);
  const labels: Record<string, string> = {
    performance_ready: '可直接演奏',
    playable_but_low_confidence: '可播放，但系統信心不足',
    needs_better_source: '需要更好的來源音檔',
    not_ready: '系統未能可靠完成',
  };
  const deliveryLabel = verifiedPerformanceScore
    ? '可直接演奏'
    : gate.verdict === 'performance_ready'
      ? '可播放草稿，需人工確認'
      : labels[gate.verdict] ?? '系統未能可靠完成';
  const alignment = gate.audio_alignment?.onset_alignment_rate;
  const blockingIssues = gate.blocking_issues ?? [];
  const verificationStatus =
    verifiedPerformanceScore
      ? '已通過已校準自動交付驗證'
      : gate.ground_truth_verified
        ? '已由對照 MIDI 驗證'
        : gate.real_audio_verified
          ? '已由真實音訊證據驗證'
          : '未完成真實音訊對照驗證';
  return (
    <section className={`performanceDeliveryPanel ${gate.verdict}`}>
      <div className="qualityStatusHeader">
        <div>
          <strong>{deliveryLabel}</strong>
          <span>自動演奏交付判定</span>
        </div>
        <span>{verificationStatus}</span>
      </div>
      <div className="qualityStatusGrid">
        <Metric label="Performance MIDI" value={gate.midi?.playback_ready === true ? '可播放' : '未驗證'} />
        <Metric label="MusicXML" value={gate.musicxml?.parseable === true ? '可讀取' : '未驗證'} />
        <Metric label="音訊 onset 對齊" value={typeof alignment === 'number' ? `${Math.round(alignment * 100)}%` : '未取得'} />
        <Metric label="核心 groove" value={gate.playability?.core_groove_stable === true ? '穩定' : '未確認'} />
      </div>
      {blockingIssues.length ? (
        <p className="qualityStatusNote">系統限制：{blockingIssues.map(qualityLimitationLabel).join('、')}</p>
      ) : gate.verdict === 'performance_ready' && !verifiedPerformanceScore ? (
        <p className="qualityStatusNote">已完成部分自動檢查，但缺少 verified delivery contract，因此不可標示為可直接演奏成品。</p>
      ) : gate.verdict === 'playable_but_low_confidence' ? (
        <p className="qualityStatusNote">已通過可播放與結構檢查，但沒有真實 full-mix 對照 MIDI 的自動驗證，因此只交付低信心草稿。</p>
      ) : (
        <p className="qualityStatusNote">系統已完成節奏、可演奏性與音訊對齊檢查。</p>
      )}
    </section>
  );
}

function performanceExportLabel(type: string, verifiedPerformanceScore: boolean): string {
  const prefix = verifiedPerformanceScore ? 'Performance' : 'Drum Draft';
  if (type === 'midi') return `${prefix} MIDI`;
  if (type === 'musicxml') return `${prefix} MusicXML`;
  if (type === 'pdf') return `${prefix} PDF`;
  return `${prefix} ${type.toUpperCase()}`;
}

type PerformanceGate = NonNullable<NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['quality']>['performance_gate']>;

function isVerifiedPerformanceScore(gate: PerformanceGate | null | undefined): boolean {
  return Boolean(
    gate
    && gate.verdict === 'performance_ready'
    && gate.delivery_allowed === true
    && gate.delivery_status === 'verified_performance_score',
  );
}

export function PracticePlaybackPanel({
  timeline,
}: {
  timeline: TranscriptionResultResponse['review_timeline'];
}) {
  const events = timeline?.performance_playback?.events ?? [];
  const audioSources = timeline?.audio_sources ?? [];
  const original = audioSources.find((source) => source.kind === 'original');
  const accompaniment = audioSources.find((source) => source.kind === 'accompaniment');
  const hasChart = Boolean(timeline?.performance_playback?.available && events.length);
  const [mode, setMode] = useState<'original' | 'chart' | 'accompaniment'>(() => preferredPracticeMode(hasChart, Boolean(original?.available)));
  const [playing, setPlaying] = useState(false);
  const [audioVolume, setAudioVolume] = useState(75);
  const [drumVolume, setDrumVolume] = useState(45);
  const [currentTime, setCurrentTime] = useState(0);
  const [audioError, setAudioError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const timers = useRef<number[]>([]);
  const animationFrame = useRef<number | null>(null);
  const playbackSession = useRef(0);
  const activeAudio = mode === 'original' ? original : mode === 'accompaniment' ? accompaniment : null;
  const duration = Math.max(events.at(-1)?.time_seconds ?? 0, timeline?.measures.at(-1)?.end_seconds ?? 0);

  const clearScheduled = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
    if (animationFrame.current !== null) window.cancelAnimationFrame(animationFrame.current);
    animationFrame.current = null;
  };
  const stop = () => {
    playbackSession.current += 1;
    clearScheduled();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    void contextRef.current?.close();
    contextRef.current = null;
    setPlaying(false);
    setCurrentTime(0);
  };
  useEffect(() => () => {
    playbackSession.current += 1;
    clearScheduled();
    if (audioRef.current) audioRef.current.pause();
    void contextRef.current?.close();
  }, []);

  if (!hasChart && !original?.available) return null;
  const currentMeasure = measureIndexForPlaybackTime(timeline?.measures ?? [], currentTime);
  const scheduleChart = (context: AudioContext, startAt: number) => {
    for (const event of events) {
      if (event.time_seconds < startAt) continue;
      const timer = window.setTimeout(() => {
        playDrumPreview(context, context.currentTime + 0.01, event.drum, event.velocity, drumVolume / 100);
      }, Math.max(0, (event.time_seconds - startAt) * 1000));
      timers.current.push(timer);
    }
  };
  const playFrom = async (requestedStartAt: number) => {
    clearScheduled();
    setAudioError(null);
    const startAt = Math.max(0, Math.min(duration, requestedStartAt));
    const session = ++playbackSession.current;
    if (activeAudio?.playback_url) {
      const audio = audioRef.current;
      if (!audio) return;
      audio.src = downloadUrl(activeAudio.playback_url);
      audio.volume = audioVolume / 100;
      audio.currentTime = startAt;
      try {
        await audio.play();
      } catch {
        if (playbackSession.current !== session) return;
        clearScheduled();
        audio.pause();
        setPlaying(false);
        setAudioError('瀏覽器無法開始音訊播放。請點選播放後再試一次。');
        return;
      }
      if (playbackSession.current !== session) return;
    }
    if (mode !== 'original') {
      const AudioContextConstructor = typeof window === 'undefined' ? undefined : window.AudioContext
        ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextConstructor) {
        if (!isCurrentPlaybackSession(playbackSession.current, session)) return;
        stop();
        setAudioError('此瀏覽器不支援鼓譜試聽；仍可播放原曲或下載 MIDI。');
        return;
      }
      let context: AudioContext | null = null;
      try {
        context = new AudioContextConstructor();
        contextRef.current = context;
        await context.resume();
        if (!isCurrentPlaybackSession(playbackSession.current, session)) {
          void context.close();
          return;
        }
        scheduleChart(context, startAt);
      } catch {
        const cleanedCurrentSession = cleanupFailedChartStart({
          activeSession: playbackSession.current,
          failedSession: session,
          failedContext: context,
          activeContext: contextRef.current,
          clearScheduled,
          releaseActiveContext: () => { contextRef.current = null; },
          pauseAudio: () => audioRef.current?.pause(),
        });
        if (!cleanedCurrentSession) return;
        setPlaying(false);
        setAudioError('瀏覽器未允許鼓譜試聽；仍可下載 MIDI。');
        return;
      }
    }
    const startedAt = performance.now();
    const updateTime = () => {
      const nextTime = activeAudio?.playback_url && audioRef.current
        ? audioRef.current.currentTime
        : startAt + elapsedPlaybackSeconds(startedAt, performance.now());
      setCurrentTime(duration > 0 ? Math.min(duration, nextTime) : nextTime);
      const audioStillPlaying = Boolean(
        activeAudio?.playback_url && audioRef.current && !audioRef.current.paused && !audioRef.current.ended,
      );
      const chartStillPlaying = !activeAudio?.playback_url && nextTime < duration;
      if (audioStillPlaying || chartStillPlaying) {
        animationFrame.current = window.requestAnimationFrame(updateTime);
      } else {
        stop();
      }
    };
    animationFrame.current = window.requestAnimationFrame(updateTime);
    if (!activeAudio?.playback_url && duration > 0) {
      timers.current.push(window.setTimeout(stop, Math.max(0, duration - startAt) * 1000 + 600));
    }
    setPlaying(true);
  };
  const play = () => { void playFrom(currentTime); };
  const seek = (value: number) => {
    const next = Math.max(0, Math.min(duration, value));
    if (playing) stop();
    setCurrentTime(next);
  };
  return (
    <section className="practicePlaybackPanel">
      <audio ref={audioRef} onEnded={stop} preload="metadata" />
      <div className="qualityStatusHeader">
        <div><strong>同步練習 / 瀏覽器內試聽</strong><span>原曲不疊鼓；伴奏模式會使用去鼓後伴奏加上鼓譜。</span></div>
        <div className="playbackActions">
          <button type="button" className="secondaryButton compactButton" onClick={playing ? stop : play}>{playing ? '停止' : mode === 'chart' ? '播放鼓譜' : '播放'}</button>
          <button type="button" className="secondaryButton compactButton" onClick={() => { stop(); window.setTimeout(() => void playFrom(0), 0); }}>重播</button>
        </div>
      </div>
      <div className="practiceModes" role="group" aria-label="練習播放模式">
        <button type="button" className={mode === 'original' ? 'selected' : ''} onClick={() => { stop(); setMode('original'); }} disabled={!original?.available}>原曲</button>
        <button type="button" className={mode === 'chart' ? 'selected' : ''} onClick={() => { stop(); setMode('chart'); }} disabled={!hasChart}>鼓譜單獨</button>
        <button type="button" className={mode === 'accompaniment' ? 'selected' : ''} onClick={() => { stop(); setMode('accompaniment'); }} disabled={!accompaniment?.available}>伴奏加鼓譜</button>
      </div>
      {!accompaniment?.available ? <p className="previewFallback">伴奏 stem 未取得；仍可使用原曲或鼓譜單獨模式。</p> : null}
      <div className="playbackControls practiceControls">
        <label><span>{mode === 'chart' ? '鼓譜音量' : '原曲／伴奏音量'}</span><input type="range" min="0" max="100" value={mode === 'chart' ? drumVolume : audioVolume} onChange={(event) => mode === 'chart' ? setDrumVolume(Number(event.currentTarget.value)) : setAudioVolume(Number(event.currentTarget.value))} /><strong>{mode === 'chart' ? drumVolume : audioVolume}%</strong></label>
        {mode === 'accompaniment' ? <label><span>鼓譜音量</span><input type="range" min="0" max="100" value={drumVolume} onChange={(event) => setDrumVolume(Number(event.currentTarget.value))} /><strong>{drumVolume}%</strong></label> : null}
        {duration > 0 ? <label><span>播放位置</span><input type="range" min="0" max={duration} step="0.1" value={Math.min(duration, currentTime)} onChange={(event) => seek(Number(event.currentTarget.value))} /><strong>{formatPlaybackTime(currentTime)}</strong></label> : null}
        <span className="playbackStatus">{playing ? `播放中${currentMeasure ? ` · 第 ${currentMeasure} 小節` : ''}` : '待播放'}</span>
      </div>
      {audioError ? <p className="previewFallback">{audioError}</p> : null}
    </section>
  );
}

export function preferredPracticeMode(
  hasChart: boolean,
  originalAvailable: boolean,
): 'original' | 'chart' {
  return hasChart || !originalAvailable ? 'chart' : 'original';
}

export function isCurrentPlaybackSession(activeSession: number, session: number): boolean {
  return activeSession === session;
}

export function elapsedPlaybackSeconds(startedAtMs: number, nowMs: number): number {
  return Math.max(0, (nowMs - startedAtMs) / 1000);
}

type ClosableAudioContext = Pick<AudioContext, 'close'>;

export function cleanupFailedChartStart({
  activeSession,
  failedSession,
  failedContext,
  activeContext,
  clearScheduled,
  releaseActiveContext,
  pauseAudio,
}: {
  activeSession: number;
  failedSession: number;
  failedContext: ClosableAudioContext | null;
  activeContext: ClosableAudioContext | null;
  clearScheduled: () => void;
  releaseActiveContext: () => void;
  pauseAudio: () => void;
}): boolean {
  if (!isCurrentPlaybackSession(activeSession, failedSession)) {
    void failedContext?.close();
    return false;
  }
  clearScheduled();
  if (activeContext === failedContext) {
    void failedContext?.close();
    releaseActiveContext();
  }
  pauseAudio();
  return true;
}

export function PerformancePlaybackPanel({
  timeline,
}: {
  timeline: TranscriptionResultResponse['review_timeline'];
}) {
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(45);
  const [currentTime, setCurrentTime] = useState<number | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const timers = useRef<number[]>([]);
  const contextRef = useRef<AudioContext | null>(null);
  const playback = timeline?.performance_playback;
  const events = playback?.events ?? [];

  const clearPlaybackTimers = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  };

  const stop = () => {
    clearPlaybackTimers();
    void contextRef.current?.close();
    contextRef.current = null;
    setPlaying(false);
    setCurrentTime(null);
  };

  useEffect(() => {
    return () => {
      clearPlaybackTimers();
      void contextRef.current?.close();
      contextRef.current = null;
    };
  }, []);

  if (!playback?.available || !events.length) return null;

  const currentMeasure = currentTime === null ? null : measureIndexForPlaybackTime(timeline?.measures ?? [], currentTime);
  const play = () => {
    stop();
    setAudioError(null);
    if (typeof window === 'undefined') return;
    const AudioContextConstructor = window.AudioContext
      ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) {
      setAudioError('此瀏覽器不支援內建試聽。請改用 MIDI / MusicXML 下載。');
      return;
    }
    let context: AudioContext;
    try {
      context = new AudioContextConstructor();
    } catch {
      setAudioError('此瀏覽器不支援內建試聽。請改用 MIDI / MusicXML 下載。');
      return;
    }
    contextRef.current = context;
    if (typeof context.resume === 'function') {
      void context.resume().catch(() => {
        stop();
        setAudioError('此瀏覽器不支援內建試聽。請改用 MIDI / MusicXML 下載。');
      });
    }
    events.forEach((event) => {
      const timer = window.setTimeout(() => {
        setCurrentTime(event.time_seconds);
        playDrumPreview(context, context.currentTime + 0.01, event.drum, event.velocity, volume / 100);
      }, Math.max(0, event.time_seconds * 1000));
      timers.current.push(timer);
    });
    const last = events[events.length - 1];
    timers.current.push(window.setTimeout(stop, last.time_seconds * 1000 + 700));
    setPlaying(true);
  };
  return (
    <section className="performanceDeliveryPanel">
      <div className="qualityStatusHeader">
        <div>
          <strong>瀏覽器內試聽</strong>
          <span>使用 simplified performance chart，而非完整偵測事件</span>
        </div>
        <div className="playbackActions">
          <button type="button" className="secondaryButton compactButton" onClick={playing ? stop : play}>
            {playing ? '停止' : '播放鼓譜'}
          </button>
          <button type="button" className="secondaryButton compactButton" onClick={play}>
            重播
          </button>
        </div>
      </div>
      <div className="playbackControls">
        <label>
          <span>音量</span>
          <input
            type="range"
            min="0"
            max="100"
            value={volume}
            onChange={(event) => setVolume(Number(event.currentTarget.value))}
            aria-label="試聽音量"
          />
          <strong>{volume}%</strong>
        </label>
        <span className="playbackStatus">
          {playing
            ? `播放中：${formatPlaybackTime(currentTime ?? 0)}${currentMeasure ? ` · 第 ${currentMeasure} 小節` : ''}`
            : '待播放'}
        </span>
      </div>
      {audioError ? <p className="previewFallback">{audioError}</p> : null}
    </section>
  );
}

function playDrumPreview(context: AudioContext, when: number, drum: string, velocity: number, volume: number) {
  const intensity = drumPreviewIntensity(velocity, volume);
  if (intensity <= 0) return;
  if (drum === 'kick') {
    playKickPreview(context, when, intensity);
    return;
  }
  if (drum === 'snare') {
    playSnarePreview(context, when, intensity);
    return;
  }
  if (drum === 'tom') {
    playTomPreview(context, when, intensity);
    return;
  }
  playHatPreview(context, when, intensity, drum === 'open_hat' || drum === 'cymbal');
}

function playKickPreview(context: AudioContext, when: number, intensity: number) {
  const gain = context.createGain();
  const oscillator = context.createOscillator();
  oscillator.type = 'sine';
  oscillator.frequency.setValueAtTime(120, when);
  oscillator.frequency.exponentialRampToValueAtTime(48, when + 0.12);
  gain.gain.setValueAtTime(intensity * 0.9, when);
  gain.gain.exponentialRampToValueAtTime(0.001, when + 0.18);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(when);
  oscillator.stop(when + 0.2);
}

function playSnarePreview(context: AudioContext, when: number, intensity: number) {
  playNoiseHit(context, when, {
    duration: 0.13,
    filterType: 'bandpass',
    frequency: 1700,
    gain: intensity * 0.42,
    q: 0.9,
  });
  const bodyGain = context.createGain();
  const body = context.createOscillator();
  body.type = 'triangle';
  body.frequency.setValueAtTime(185, when);
  bodyGain.gain.setValueAtTime(intensity * 0.12, when);
  bodyGain.gain.exponentialRampToValueAtTime(0.001, when + 0.09);
  body.connect(bodyGain).connect(context.destination);
  body.start(when);
  body.stop(when + 0.1);
}

function playTomPreview(context: AudioContext, when: number, intensity: number) {
  const gain = context.createGain();
  const oscillator = context.createOscillator();
  oscillator.type = 'sine';
  oscillator.frequency.setValueAtTime(155, when);
  oscillator.frequency.exponentialRampToValueAtTime(105, when + 0.14);
  gain.gain.setValueAtTime(intensity * 0.45, when);
  gain.gain.exponentialRampToValueAtTime(0.001, when + 0.2);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(when);
  oscillator.stop(when + 0.22);
}

function playHatPreview(context: AudioContext, when: number, intensity: number, open: boolean) {
  playNoiseHit(context, when, {
    duration: open ? 0.18 : 0.055,
    filterType: 'highpass',
    frequency: 5200,
    gain: intensity * (open ? 0.18 : 0.13),
    q: 0.65,
  });
}

function playNoiseHit(
  context: AudioContext,
  when: number,
  options: { duration: number; filterType: BiquadFilterType; frequency: number; gain: number; q: number },
) {
  if (options.gain <= 0) return;
  const sampleCount = Math.max(1, Math.floor(context.sampleRate * options.duration));
  const buffer = context.createBuffer(1, sampleCount, context.sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < sampleCount; index += 1) {
    channel[index] = (Math.random() * 2 - 1) * (1 - index / sampleCount);
  }
  const source = context.createBufferSource();
  const filter = context.createBiquadFilter();
  const gain = context.createGain();
  source.buffer = buffer;
  filter.type = options.filterType;
  filter.frequency.setValueAtTime(options.frequency, when);
  filter.Q.setValueAtTime(options.q, when);
  gain.gain.setValueAtTime(Math.max(0.001, options.gain), when);
  gain.gain.exponentialRampToValueAtTime(0.001, when + options.duration);
  source.connect(filter).connect(gain).connect(context.destination);
  source.start(when);
  source.stop(when + options.duration);
}

export function drumPreviewIntensity(velocity: number, volume: number): number {
  if (volume <= 0) return 0;
  return Math.max(0.04, Math.min(1, velocity / 127)) * Math.min(1, volume);
}

export function measureIndexForPlaybackTime(
  measures: NonNullable<TranscriptionResultResponse['review_timeline']>['measures'],
  timeSeconds: number,
): number | null {
  const match = measures.find((measure) => {
    const start = measure.start_seconds;
    const end = measure.end_seconds;
    return typeof start === 'number' && typeof end === 'number' && timeSeconds >= start && timeSeconds < end;
  });
  if (match) return match.measure_index;
  const previous = [...measures]
    .reverse()
    .find((measure) => typeof measure.start_seconds === 'number' && timeSeconds >= measure.start_seconds);
  return previous?.measure_index ?? null;
}

function formatPlaybackTime(seconds: number): string {
  return `${seconds.toFixed(1)}s`;
}

function ReviewPacketPanel({ result }: { result: TranscriptionResultResponse }) {
  const performance = result.pipeline?.quality?.performance_gate;
  const verifiedPerformanceScore = isVerifiedPerformanceScore(performance);
  const jsonUrl = `/api/v1/transcriptions/${encodeURIComponent(result.job_id)}/review-packet`;
  const zipUrl = `/api/v1/transcriptions/${encodeURIComponent(result.job_id)}/download/review-packet`;

  return (
    <div className="reviewPacketPanel">
      <div className="reviewHeader">
        <strong>自動交付包</strong>
        <span>performance artifacts + verification</span>
      </div>
      <div className="downloadGrid compactDownloads">
        <a className="downloadButton" href={jsonUrl}>
          JSON
          <span>quality summary</span>
        </a>
        <a className="downloadButton" href={zipUrl}>
          ZIP
          <span>performance artifacts</span>
        </a>
      </div>
      <div className="exportList compact">
        {result.exports.map((item) => (
          <div className="exportRow" key={`packet-${item.type}`}>
            <span>{item.type.toUpperCase()}</span>
            <span>{item.type === 'pdf' && item.status !== 'available' ? `${item.status} · optional` : item.status}</span>
          </div>
        ))}
      </div>
      <p className="qualityStatusNote">
        {verifiedPerformanceScore
          ? '此交付包已通過自動播放、節奏、可演奏性與音訊對齊檢查。'
          : '此交付包保留自動品質結果；系統未通過時不將譜面包裝成可直接演奏。'}
      </p>
    </div>
  );
}

function unknownQualityVerdict(
  validation: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['validation']> | null,
): QualityVerdict {
  const musicxmlAvailable = Boolean(validation?.musicxml.available);
  const musicxmlParseable = Boolean(validation?.musicxml.parseable);
  return {
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
      musicxml_available: musicxmlAvailable,
      musicxml_parseable: musicxmlParseable,
    },
    musicxml_available: musicxmlAvailable,
    musicxml_parseable: musicxmlParseable,
  };
}

function qualityVerdictLabel(verdict: string): string {
  if (verdict === 'mvp_candidate') return '接近可用草稿';
  if (verdict === 'draft_candidate_needs_review') return '草稿品質仍需提升';
  if (verdict === 'not_candidate') return '系統不建議交付此草稿';
  return '品質狀態未知';
}

function qualityVerdictTone(verdict: string): 'ready' | 'warn' | 'error' | 'unknown' {
  if (verdict === 'mvp_candidate') return 'ready';
  if (verdict === 'draft_candidate_needs_review') return 'warn';
  if (verdict === 'not_candidate') return 'error';
  return 'unknown';
}

function qualityLimitationLabel(limitation: string): string {
  const labels: Record<string, string> = {
    hihat_missing_likely: 'Hi-hat 可能缺失',
    kick_missing: 'Kick 缺失',
    musicxml_unavailable: 'MusicXML 未產出',
    musicxml_unparseable: 'MusicXML 無法解析',
    no_snare_detected: 'Snare 未偵測到',
    quality_verdict_unavailable: '尚未產生品質判斷',
    snare_missing: 'Snare 缺失',
    tom_false_positive_likely: 'Tom 誤判偏多',
    audio_onset_alignment_low: '與分離鼓聲的 onset 對齊不足',
    audio_onset_alignment_unavailable: '無法取得分離鼓聲 onset 對齊結果',
    core_drum_missing: '缺少可演奏的 kick、snare 或 hi-hat',
    core_groove_unstable: '主 groove 不夠穩定',
    measure_duration_incomplete: '小節節奏時值不完整',
    notation_fragmented_groove_rhythm: '節奏仍有零碎片段',
    notation_chart_still_dense: '譜面仍過於密集',
    performance_midi_unparseable: 'Performance MIDI 無法播放驗證',
    performance_musicxml_unparseable: 'Performance MusicXML 無法讀取',
    tom_outside_fill: 'Tom 出現在非 fill 的主 groove',
    unplayable_hand_conflict: '偵測到不合理的手部衝突',
  };
  return labels[limitation] ?? limitation.replaceAll('_', ' ');
}

function qualityTomFilterLabel(status: string): string {
  const labels: Record<string, string> = {
    applied: '已套用 tom filter',
    disabled: '未套用 tom filter',
    no_op_ratio_within_target: 'Tom filter 未啟動：比例已達標',
    no_safe_tom_filter_change: 'Tom 誤判仍偏多',
    skipped_missing_core_groove: 'Tom filter 未啟動：核心節奏不足',
    unsupported_preset: 'Tom filter preset 不支援',
  };
  return labels[status] ?? 'Tom filter 狀態未知';
}

function notationReadabilityLabel(readability: Record<string, unknown>): string {
  if (!readability || Object.keys(readability).length === 0) return '未回報';
  const warnings = Array.isArray(readability.warnings) ? readability.warnings : [];
  if (warnings.includes('notation_dense_full_mix_likely')) return '譜面偏密，系統不建議直接交付';
  if (readability.has_hand_voice && readability.has_foot_voice) return '雙聲部鼓譜';
  if (readability.has_hand_voice || readability.has_foot_voice) return '單聲部鼓譜';
  return '需檢查';
}

function notationChartLabel(chart: Record<string, unknown>): string {
  if (!chart || Object.keys(chart).length === 0) return '未回報';
  const mode =
    chart.mode === 'readable_drum_chart_v3'
      ? '逐小節可讀鼓譜'
      : chart.mode === 'readable_drum_chart_v2'
      ? '可讀鼓譜'
      : chart.mode === 'simplified_chart_v1'
        ? '簡化鼓譜'
        : '完整轉錄';
  const chartCount = typeof chart.chart_event_count === 'number' ? chart.chart_event_count : null;
  const originalCount = typeof chart.original_event_count === 'number' ? chart.original_event_count : null;
  if (chartCount !== null && originalCount !== null) return `${mode} ${chartCount}/${originalCount}`;
  return mode;
}

function qualitySuggestionList(
  limitations: string[],
  musicxmlParseable: boolean,
  notationReadability: Record<string, unknown> = {},
  notationChart: Record<string, unknown> = {},
): string[] {
  const suggestions = new Set<string>();
  if (!musicxmlParseable) {
    suggestions.add('系統未能確認 MusicXML 可讀取，因此不會將此結果標示為可直接演奏。');
  }
  const readabilityWarnings = Array.isArray(notationReadability.warnings) ? notationReadability.warnings : [];
  if (readabilityWarnings.includes('notation_dense_full_mix_likely')) {
    suggestions.add('這份 full-mix 譜面仍偏密；系統會保留技術 artifacts，但不應視為完成 performance score。');
  }
  if (readabilityWarnings.includes('generic_tom_position_used')) {
    suggestions.add('Tom 位置使用保守通用表示；目前不會宣稱其細節已自動驗證。');
  }
  const chartWarnings = Array.isArray(notationChart.warnings) ? notationChart.warnings : [];
  if (notationChart.mode === 'readable_drum_chart_v3') {
    suggestions.add('MusicXML 已使用逐小節可讀鼓譜；完整 processed events 仍保留於 MIDI。');
  } else if (notationChart.mode === 'readable_drum_chart_v2') {
    suggestions.add('MusicXML 已使用可讀鼓譜模式；MIDI 仍保留完整 processed events。');
  } else if (notationChart.mode === 'simplified_chart_v1') {
    suggestions.add('MusicXML 已使用簡化鼓譜模式；MIDI 仍保留完整 processed events。');
  }
  if (chartWarnings.includes('no_stable_groove_detected')) {
    suggestions.add('未偵測到足夠穩定的 groove；系統會降低交付信心，而非把它標示為完成品。');
  }
  if (chartWarnings.includes('notation_fill_density_needs_review')) {
    suggestions.add('Tom fill 偵測仍偏多；系統會將此視為品質限制。');
  }
  if (chartWarnings.includes('notation_chart_still_dense')) {
    suggestions.add('簡化後仍有過密小節；系統不會將這份譜標示為可直接演奏。');
  }
  if (chartWarnings.includes('notation_fragmented_groove_rhythm')) {
    suggestions.add('部分 groove 節奏仍過於零碎；系統會阻止正式 performance score 交付。');
  }
  for (const limitation of limitations) {
    if (limitation === 'tom_false_positive_likely') {
      suggestions.add('Tom 誤判可能偏多；系統將此列為自動品質限制。');
    } else if (limitation === 'hihat_missing_likely') {
      suggestions.add('Hi-hat 節奏可能缺失；系統將降低自動交付信心。');
    } else if (limitation === 'no_snare_detected' || limitation === 'snare_missing') {
      suggestions.add('Snare backbeat 證據不足；系統不會將此結果標示為完成品。');
    } else if (limitation === 'kick_missing') {
      suggestions.add('Kick downbeat 證據不足；系統不會將此結果標示為完成品。');
    } else if (limitation === 'quality_verdict_unavailable') {
      suggestions.add('這份結果缺少自動品質判斷，因此系統不會將其標示為可直接演奏。');
    }
  }
  return [...suggestions];
}

function pipelineModeLabel(mode: string): string {
  if (mode === 'true_ai') return 'True-AI';
  if (mode === 'demo_mock' || mode === 'mock') return 'Demo / mock';
  return 'Unknown';
}

function MusicXmlPreview({
  url,
  validation,
  fullWidth = false,
}: {
  url: string | null;
  validation: NonNullable<NonNullable<TranscriptionResultResponse['pipeline']>['validation']> | null;
  fullWidth?: boolean;
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
  const visualQa = validation?.visual_qa;
  const visualQaStatus = visualQa ? visualQaLabel(visualQa.status) : 'not reported';
  const showCanvas = Boolean(url) && status !== 'unavailable' && status !== 'error';

  return (
    <div className={fullWidth ? 'musicXmlPreview fullWidthPreview' : 'musicXmlPreview'}>
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
        <ValidationStatus label="Visual QA" status={visualQaStatus} warnings={[]} />
      </div>
      {visualQa?.status === 'musescore_gui_session_unavailable' ? (
        <p className="previewFallback">已產生 MusicXML；瀏覽器視覺預覽目前不可用，但下載與自動驗證不受影響。</p>
      ) : null}
      {showCanvas ? (
        <div className="musicXmlCanvas">
          <div className="musicXmlRenderTarget" ref={renderTargetRef} />
        </div>
      ) : null}
      {status === 'unavailable' ? <p className="previewFallback">MusicXML preview unavailable</p> : null}
      {status === 'loading' || status === 'idle' ? <p className="previewFallback">Loading preview</p> : null}
      {status === 'error' ? (
        <p className="previewFallback">Preview renderer unavailable; download remains available.</p>
      ) : null}
    </div>
  );
}

function visualQaLabel(status: string): string {
  if (status === 'completed') return 'rendered';
  if (status === 'musescore_gui_session_unavailable') return '本機視覺預覽不可用';
  if (status === 'renderer_unavailable') return 'renderer unavailable';
  if (status === 'render_failed') return 'needs review';
  return 'not requested';
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

function pipelineConfigInput(mode: PipelineModeSelection): PipelineRunConfigInput {
  if (mode === 'true_ai') {
    return {
      pipelineMode: 'true_ai',
      adtofThresholdPreset: TRUE_AI_THRESHOLD_PRESET,
      tomFilterPreset: TRUE_AI_TOM_FILTER_PRESET,
    };
  }
  return { pipelineMode: 'demo_mock' };
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

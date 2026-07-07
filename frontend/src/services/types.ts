export type RuntimePreflightStatus = 'ready' | 'degraded' | 'not_ready' | 'error';

export interface RuntimePreflightResponse {
  status: RuntimePreflightStatus;
  mock_ai_ready: boolean;
  true_ai_ready: boolean;
  missing_requirements: string[];
  checks: Record<string, unknown>;
  smoke_commands: Record<string, string>;
  checked_at: string;
  error: { code: string; message: string } | null;
}

export interface UploadAcceptedResponse {
  job_id: string;
  status: string;
  status_url: string;
  result_url: string;
  created_at: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  error: {
    code: string | null;
    message: string | null;
    stage: string | null;
    retriable: boolean;
  } | null;
  created_at: string;
  queued_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  failed_at?: string | null;
}

export interface TranscriptionJobSummary {
  job_id: string;
  title: string | null;
  file_name: string;
  status: string;
  stage: string;
  progress: number;
  created_at: string;
  completed_at: string | null;
  failed_at: string | null;
  exports: Record<string, string>;
  error: {
    code: string | null;
    message: string | null;
    stage: string | null;
    retriable: boolean;
  } | null;
}

export interface TranscriptionJobListResponse {
  jobs: TranscriptionJobSummary[];
  limit: number;
}

export interface LocalDataSummaryResponse {
  schema_version: string;
  status: string;
  dry_run: boolean;
  execute_supported: boolean;
  storage_root_name: string;
  job_dir_count: number;
  database_status: string;
  database_job_count: number | null;
  orphan_job_dir_count: number;
  warnings: string[];
}

export interface TranscriptionResultResponse {
  job_id: string;
  status: string;
  stage: string;
  title: string | null;
  created_at: string;
  completed_at: string | null;
  audio: {
    id: string;
    file_name: string;
    content_type: string;
    file_size_bytes: number;
    duration_seconds: number | null;
    sample_rate: number | null;
    channels: number | null;
  };
  drum_track: {
    id: string;
    estimated_bpm: number | null;
    time_signature: string;
    event_count: number;
    confidence_label: string | null;
    warnings: string[];
  } | null;
  preview: {
    musicxml_url: string | null;
  };
  exports: Array<{
    type: string;
    status: string;
    content_type: string;
    file_size_bytes: number | null;
    checksum: string | null;
    download_url: string | null;
  }>;
  pipeline?: {
    mode: 'mock' | 'true_ai' | 'unknown' | string;
    status: string | null;
    stages: Array<{
      name: string;
      status: string;
      runtime_seconds: number | null;
      warnings: string[];
    }>;
    artifacts: Array<{
      type: string;
      available: boolean;
      file_size_bytes: number | null;
      status: string | null;
    }>;
    warnings: string[];
    quality?: {
      raw_event_count: number | null;
      processed_event_count: number | null;
      raw_note_histogram: Record<string, number>;
      processed_drum_counts: Record<string, number>;
      duration_seconds: number | null;
      tempo_bpm: number | null;
      estimated_measure_count: number | null;
      quality_flags: string[];
      warnings: string[];
    } | null;
    validation?: {
      musicxml: {
        available: boolean;
        parseable: boolean | null;
        error_code: string | null;
        warnings: string[];
      };
      pdf: {
        available: boolean;
        optional: boolean | null;
        openable: boolean | null;
        error_code: string | null;
        warnings: string[];
      };
    } | null;
    pipeline_log_available: boolean;
  } | null;
}

export interface ReviewPacketResponse {
  schema_version: string;
  status: string;
  job: Record<string, unknown>;
  audio: Record<string, unknown>;
  exports: Array<{
    type: string;
    status: string;
    optional: boolean;
    content_type: string;
    file_size_bytes: number | null;
    download_url: string | null;
    included_in_zip: boolean;
  }>;
  quality?: TranscriptionResultResponse['pipeline'] extends infer Pipeline
    ? Pipeline extends { quality?: infer Quality }
      ? Quality
      : unknown
    : unknown;
  validation?: TranscriptionResultResponse['pipeline'] extends infer Pipeline
    ? Pipeline extends { validation?: infer Validation }
      ? Validation
      : unknown
    : unknown;
  review_checklist: Array<{ code: string; label: string; detail: string }>;
  manual_eval_seed: Record<string, unknown>;
  redaction: { status: string; unsafe_tokens: string[] };
}

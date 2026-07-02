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
}

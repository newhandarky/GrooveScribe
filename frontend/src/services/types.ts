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

export type PipelineModeSelection = 'demo_mock' | 'true_ai';

export interface PipelineRunConfigInput {
  pipelineMode?: PipelineModeSelection;
  adtofThresholdPreset?: string | null;
  tomFilterPreset?: string | null;
}

export interface PipelineConfigSummary {
  mode: string;
  adtof_threshold_preset: string | null;
  tom_filter_preset: string | null;
  runtime_fallback_status: string | null;
  source_job_id: string | null;
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
  source_job_id: string | null;
  title: string | null;
  file_name: string;
  status: string;
  stage: string;
  progress: number;
  created_at: string;
  completed_at: string | null;
  failed_at: string | null;
  exports: Record<string, string>;
  pipeline_config: PipelineConfigSummary;
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
  source_job_id: string | null;
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
  review_timeline?: {
    schema_version: string;
    timing_source: string;
    tempo_bpm: number | null;
    audio_sources: Array<{
      kind: 'original' | 'drums_stem' | string;
      label: string;
      available: boolean;
      playback_url: string | null;
    }>;
    measures: Array<{
      measure_index: number;
      start_seconds: number | null;
      end_seconds: number | null;
      render_kind: string;
      drum_counts: Record<string, number>;
      warnings: string[];
    }>;
    performance_playback?: {
      available: boolean;
      event_count: number;
      events: Array<{ time_seconds: number; drum: string; velocity: number }>;
    };
  };
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
    config: PipelineConfigSummary;
    quality?: {
      raw_event_count: number | null;
      processed_event_count: number | null;
      raw_note_histogram: Record<string, number>;
      processed_drum_counts: Record<string, number>;
      duration_seconds: number | null;
      tempo_bpm: number | null;
      tempo_source?: string | null;
      estimated_measure_count: number | null;
      musicxml_parseable?: boolean | null;
      visual_qa_status?: string | null;
      visual_qa_reason_code?: string | null;
      notation_readability: {
        schema_version?: string;
        layout_profile?: string;
        voice_count?: number | null;
        has_hand_voice?: boolean;
        has_foot_voice?: boolean;
        hand_event_count?: number | null;
        foot_event_count?: number | null;
        generic_tom_count?: number | null;
        measure_count?: number | null;
        dense_measure_count?: number | null;
        dense_measure_threshold?: number | null;
        warnings?: string[];
      };
      notation_chart: {
        schema_version?: string;
        mode?: string;
        readability_verdict?: string;
        original_event_count?: number | null;
        chart_event_count?: number | null;
        max_events_per_measure?: number | null;
        max_visible_notes_per_measure?: number | null;
        measure_count?: number | null;
        groove_measure_count?: number | null;
        repeat_measure_count?: number | null;
        fill_measure_count?: number | null;
        accent_measure_count?: number | null;
        anchor_measure_count?: number | null;
        literal_measure_count?: number | null;
        break_measure_count?: number | null;
        stable_groove_section_count?: number | null;
        complete_core_groove_measure_count?: number | null;
        incomplete_core_groove_measure_count?: number | null;
        hihat_rendered_measure_count?: number | null;
        measures_with_complete_core_groove?: number | null;
        rhythm_mode?: string;
        groove_eighth_note_count?: number | null;
        groove_sixteenth_note_count?: number | null;
        fill_sixteenth_note_count?: number | null;
        off_grid_events_snapped?: number | null;
        off_grid_events_dropped?: number | null;
        measures_with_fragmented_rests?: number | null;
        hihat_eighth_pulse_measure_count?: number | null;
        hihat_quarter_pulse_measure_count?: number | null;
        preserved_counts?: Record<string, number>;
        dropped_counts?: Record<string, number>;
        dense_measures_before?: number | null;
        dense_measures_after?: number | null;
        warnings?: string[];
      };
      quality_flags: string[];
      warnings: string[];
      postprocess_filters: Record<string, Record<string, string | number | boolean | null>>;
      quality_verdict: {
        verdict: string;
        usability_score: number | null;
        limitations: string[];
        candidate_gate: {
          status: string;
          run_completed: boolean | null;
          processed_event_count: number | null;
          min_event_count: number | null;
          kick_present: boolean | null;
          snare_present: boolean | null;
          hihat_present: boolean | null;
          blocking_flags: string[];
          musicxml_available: boolean;
          musicxml_parseable: boolean;
        };
        musicxml_available: boolean;
        musicxml_parseable: boolean;
      };
      performance_gate?: {
        schema_version: string;
        verdict: 'performance_ready' | 'playable_but_low_confidence' | 'needs_better_source' | 'not_ready' | string;
        delivery_allowed: boolean;
        ground_truth_verified: boolean;
        real_audio_verified: boolean;
        delivery_status: 'verified_performance_score' | 'playable_draft_unverified' | 'needs_better_source' | 'technical_artifacts_only' | string;
        blocking_issues?: string[];
        midi?: Record<string, string | number | boolean | null>;
        musicxml?: Record<string, string | number | boolean | null>;
        rhythm?: Record<string, string | number | boolean | null>;
        playability?: Record<string, string | number | boolean | null>;
        audio_alignment?: Record<string, string | number | boolean | null>;
      };
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
      visual_qa?: {
        status: string;
        reason_code: string | null;
        pdf_available: boolean;
        first_page_png_available: boolean;
      };
    } | null;
    pipeline_log_available: boolean;
  } | null;
  source_result_summary: {
    job_id: string | null;
    status: string;
    pipeline_config?: PipelineConfigSummary;
    quality_verdict?: {
      verdict: string;
      usability_score: number | null;
      limitations: string[];
    } | null;
    processed_drum_counts?: Record<string, number>;
    tom_filter?: Record<string, string | number | boolean | null> | null;
    musicxml_parseable?: boolean | null;
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
  pipeline_config?: PipelineConfigSummary | Record<string, unknown> | null;
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
  audio_review?: TranscriptionResultResponse['review_timeline'];
  redaction: { status: string; unsafe_token_count: number };
}

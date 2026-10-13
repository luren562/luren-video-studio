export interface Token {
  access_token: string;
  username: string;
}

export interface AIProvider {
  id: number;
  name: string;
  base_url: string;
  has_api_key: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AIModel {
  id: number;
  provider_id: number;
  name: string;
  model_id: string;
  capability: string;
  config_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface ProviderTestResult {
  ok: boolean;
  model: string;
  latency_ms: number;
  error_type: string;
  message: string;
}

export interface CoverConfig {
  base_url: string;
  has_api_key: boolean;
  model: string;
  size: string;
}

export interface Engine {
  key: string;
  display_name: string;
  description: string;
  aspect: string;
  lang: string;
  default_duration_sec: number;
  gates: Record<string, string>;
  needs_voiceover: boolean;
  needs_assets: boolean;
  needs_review_agent: boolean;
}

export interface VideoStyle {
  id: number;
  name: string;
  engine: string;
  aspect: string;
  lang: string;
  default_duration_sec: number;
  theme_json: Record<string, unknown>;
  engine_config_json: Record<string, unknown>;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
}

export interface ContentStrategy {
  id: number;
  name: string;
  description: string;
  audience: string;
  tone: string;
  content_goal: string;
  prompt_rules: string;
  banned_phrases_json: string[];
  style_guide_md: string;
  default_model_id: number | null;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
}

export interface StrategyPayload {
  name?: string;
  description?: string;
  audience?: string;
  tone?: string;
  content_goal?: string;
  prompt_rules?: string;
  banned_phrases?: string[];
  style_guide_md?: string;
  default_model_id?: number | null;
  is_default?: boolean;
  is_active?: boolean;
}

export interface VideoScene {
  id: number;
  version_id: number;
  position: number;
  role: string;
  narration_text: string;
  subtitle_chunks_json: string[];
  visual_type: string;
  card_slug: string;
  content_json: Record<string, unknown>;
  asset_ids_json: number[];
  skinning: string;
  render_status: string;
  render_error: string;
}

export interface VideoVersion {
  id: number;
  project_id: number;
  version_number: number;
  model_id: number | null;
  prompt_version: string;
  spec_json: Record<string, unknown>;
  generation_meta_json: Record<string, unknown>;
  validation_json: Record<string, unknown>;
  created_at: string;
  scenes: VideoScene[];
}

export interface VideoProject {
  id: number;
  title: string;
  topic: string;
  audience: string;
  goal: string;
  source_notes: string;
  constraints: string;
  reference_url: string;
  style_id: number | null;
  model_id: number | null;
  strategy_id: number | null;
  mode: string;
  duration_target_sec: number;
  lang: string;
  review_required: boolean;
  theme_json: { accent?: string } | null;
  bgm_enabled: boolean | null;
  tts_enabled: boolean | null;
  tts_voice: string | null;
  tts_rate: number | null;
  tts_asset_id: number | null;
  status: string;
  current_version_id: number | null;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface TtsVoice {
  id: string;
  name: string;
  localName: string;
  shortName: string;
  locale: string;
  gender: string;
  provider: string;
  providers: string[];
  styles: string[];
  is_default: boolean;
}

export interface VideoProjectDetail extends VideoProject {
  current_version: VideoVersion | null;
  latest_task_id: number | null;
  agent_summary: AgentRunSummary | null;
}

export interface AgentUsage {
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cached_tokens: number;
  total_tokens: number;
  total_budget?: number;
  prompt_budget?: number;
  completion_budget?: number;
  production?: Record<string, number>;
  review?: Record<string, number>;
  by_model?: Record<string, Record<string, number>>;
  by_phase?: Record<string, Record<string, number>>;
}

export interface AgentRunSummary {
  schema_version?: number;
  execution_id?: string | null;
  invocation_id?: string | null;
  invocation_usage?: Partial<AgentUsage>;
  budget_scope?: string;
  remaining_seconds?: number;
  unknown_usage_responses?: number;
  convergence_mode?: boolean;
  candidate_status?: string;
  candidate_stale?: boolean;
  blockers?: string[];
  stop_reason?: {code: string; detail: string} | null;
  last_progress?: {iteration: number; tool: string; at: number} | null;
  substate?: string;
  still_qa?: {status?: string; report?: {approved?: boolean; issues?: Array<{severity: string; detail: string}>}};
  visual_qa?: {status?: string; report?: {approved?: boolean}};
  still_reviews?: number;
  render_ledger?: Array<{attempt: number; reason: string; blockers_before?: number; at: number}>;
  granted_renders?: number;
  render_concurrency?: number | null;
  render_concurrency_reason?: string;
  check_ready_last?: {
    elapsed_seconds?: number;
    readiness_cached?: boolean;
    check_ready_bundle_cached?: boolean;
    ok?: boolean;
    source_hash?: string;
    at?: number;
  };
  phase: string;
  phase_label: string;
  iteration: number;
  max_iters: number;
  status: string;
  usage: AgentUsage;
  candidate_count: number;
  inspections: number;
  render_attempts: number;
  last_tool: string;
  last_tool_at: number | null;
  updated_at: number | null;
  [key: string]: unknown;
}

export interface PipelineTask {
  id: number;
  kind: string;
  resource_type: string;
  resource_id: number | null;
  status: string;
  progress_current: number;
  progress_total: number;
  attempts: number;
  max_attempts: number;
  error_code: string;
  error_message: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineEvent {
  id: number;
  task_id: number;
  level: string;
  message: string;
  data_json: Record<string, unknown>;
  created_at: string;
}

export interface GateEntry {
  key: string;
  name: string;
  status: "pass" | "fail" | "skipped" | "error";
  detail: string;
  data: Record<string, unknown>;
}

export interface GatesJson {
  render_ok?: boolean;
  message?: string;
  passed?: boolean;
  blocking?: boolean;
  skipped_reason?: string;
  gates?: GateEntry[];
  tts?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TranscriptionSummary {
  id: number;
  title: string;
  source_type: "upload" | "url";
  source_ref: string;
  language: string;
  model: string;
  status: "queued" | "running" | "succeeded" | "failed";
  duration_sec: number | null;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface TranscriptionJob extends TranscriptionSummary {
  text: string;
  segments_json: Array<{ start: number; end: number; text: string }>;
}

export interface RenderOutput {
  id: number;
  project_id: number;
  version_id: number;
  engine: string;
  width: number;
  height: number;
  fps: number;
  duration_frames: number;
  file_path: string;
  poster_path: string;
  contact_sheet_path: string;
  cover_path: string;
  cover_status: string;
  cover_error: string;
  sha256: string;
  status: string;
  gates_json: GatesJson;
  review_json: Record<string, unknown>;
  created_at: string;
}

export interface Stats {
  projects_total: number;
  projects_in_progress: number;
  outputs_total: number;
  outputs_completed: number;
  tasks_queued: number;
  tasks_running: number;
  tasks_failed: number;
}

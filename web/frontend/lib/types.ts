export type TaskStatus =
  | "pending"
  | "running"
  | "awaiting_user"
  | "completed"
  | "failed";

export type CurrentStep =
  | "generating_script"
  | "select_scripts"
  | "select_tts"
  | "generating_tts"
  | "review_tts"
  | "review_prompts"
  | "generating_video"
  | "select_clips"
  | "preview_timeline"
  | "select_template"
  | "building_capcut";

export type TtsProvider = "elevenlabs" | "typecast";

export interface TtsVoice {
  voice_id: string;
  voice_name: string;
  gender: string | null;
  age: string | null;
  use_cases: string[];
  emotions: string[];
}

export interface TtsVoicesResp {
  provider: TtsProvider;
  model: string | null;
  voices: TtsVoice[];
}

export interface TtsOptions {
  voice_id?: string;
  model?: string;
  emotion_type?: "smart" | "preset";
  emotion_preset?:
    | "normal"
    | "happy"
    | "sad"
    | "angry"
    | "whisper"
    | "toneup"
    | "tonedown";
  emotion_intensity?: number;
  audio_tempo?: number;
  audio_pitch?: number;
  volume?: number;
  audio_format?: "mp3" | "wav";
  language?: string;
  seed?: number;
}

export interface TaskSummary {
  id: number;
  product_name: string;
  status: TaskStatus;
  current_step: CurrentStep | null;
  created_at: string;
  completed_at: string | null;
  error?: string | null;
}

export interface SubProgress {
  current: number;
  total: number;
  agent: string | null;
  elapsed_sec: number;
}

export interface TaskDetail {
  id: number;
  product_name: string;
  status: TaskStatus;
  current_step: CurrentStep | null;
  sub_progress: SubProgress | null;
  progress_message?: string | null;
  original_price?: number | null;
  sale_price?: number | null;
  created_at: string;
  completed_at: string | null;
  output_dir: string | null;
  error: string | null;
  artifacts: Record<string, boolean>;
  images: string[];
  selected_variant_ids: string[];
  selected_clips: Record<string, number[]>;
  campaign_variant: string | null;
  tts_provider?: TtsProvider | null;
  tts_options?: TtsOptions | null;
  target_char_count?: number | null;
  i2v_model?: string | null;
  i2v_models_chain?: string[];
  clip_sources?: Record<string, ClipSourceEntry>;
}

export interface ClipSourceEntry {
  source: "veo" | "user";
  uploaded_at?: string;
  original_filename?: string;
  duration_sec?: number | null;
  width?: number | null;
  height?: number | null;
  model?: string;
}

export interface UploadClipResp {
  task_id: number;
  variant_id: string;
  clip_num: number;
  saved_filename: string;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  aspect_ratio_warning: string | null;
  ffprobe_skipped: boolean;
}

export interface I2VModelInfo {
  provider: string;
  model: string;
  family: string;
  label: string;
  notes: string;
  expected_sec_per_clip: number;
  daily_quota_estimate: number | null;
  quality_tier?: number | null;
  speed_tier?: number | null;
}

export interface ModelsConfigResp {
  i2v: I2VModelInfo;
  default_target_char_count: number;
}

export interface I2VModelsListResp {
  models: I2VModelInfo[];
  default_chain: string[];
  config_default: string;
}

export interface HealthResp {
  status: string;
  project_root: string;
}

export type CampaignVariant =
  | "none"
  | "family_month"
  | "children_day"
  | "parents_day"
  | "fast_delivery";

export const CAMPAIGN_VARIANTS: {
  value: CampaignVariant;
  label: string;
}[] = [
  { value: "none", label: "캠페인 미적용" },
  { value: "family_month", label: "가정의달+세일 (4.20~5.8)" },
  { value: "children_day", label: "어린이날+세일 (4.20~5.5)" },
  { value: "parents_day", label: "어버이날+세일 (5.8)" },
  { value: "fast_delivery", label: "빠른배송+세일 (상시)" },
];

export interface StrategyScene {
  scene_num: number;
  source_image: string;
  timeline?: string;
  expected_duration_sec?: number;
  scene_intent?: string;
  script_segment_brief?: string;
  i2v_prompt_baseline?: string;
  i2v_prompt_refined?: string;
}

export interface StrategyVariant {
  variant_id: string;
  hook_type?: string;
  direction?: string;
  target_emotion?: string;
  scenes?: StrategyScene[];
  clips?: {
    clip_num: number;
    source_image: string;
    i2v_prompt: string;
    timeline?: string;
  }[];
}

export interface StrategyJson {
  schema_version?: number;
  image_count?: number;
  variants?: StrategyVariant[];
}

export interface ScriptScene {
  scene_num: number;
  script_segment: string;
  i2v_prompt_refined?: string;
}

export interface ScriptEntry {
  variant_id: string;
  script_text?: string;
  full_text?: string;
  title?: string;
  hashtags?: string[];
  hook_text?: string;
  outro_text?: string;
  hook_attached_to?: number | null;
  outro_attached_to?: number | null;
  scenes?: ScriptScene[];
}

export interface ScriptsFinalJson {
  schema_version?: number;
  scripts?: ScriptEntry[];
}

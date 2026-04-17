export type TaskStatus =
  | "pending"
  | "running"
  | "awaiting_user"
  | "completed"
  | "failed";

export type CurrentStep =
  | "generating_script"
  | "select_scripts"
  | "generating_tts"
  | "review_tts"
  | "review_prompts"
  | "generating_video"
  | "select_clips"
  | "preview_timeline"
  | "select_template"
  | "building_capcut";

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
  created_at: string;
  completed_at: string | null;
  output_dir: string | null;
  error: string | null;
  artifacts: Record<string, boolean>;
  images: string[];
  selected_variant_ids: string[];
  selected_clips: Record<string, number[]>;
  campaign_variant: string | null;
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

export interface StrategyVariant {
  variant_id: string;
  hook_type?: string;
  direction?: string;
  target_emotion?: string;
  clips?: {
    clip_num: number;
    source_image: string;
    i2v_prompt: string;
    timeline?: string;
  }[];
}

export interface StrategyJson {
  variants?: StrategyVariant[];
}

export interface ScriptEntry {
  variant_id: string;
  script_text?: string;
  title?: string;
  hashtags?: string[];
  hook_text?: string;
}

export interface ScriptsFinalJson {
  scripts?: ScriptEntry[];
}

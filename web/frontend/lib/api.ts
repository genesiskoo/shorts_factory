import type {
  HealthResp,
  I2VModelsListResp,
  ModelsConfigResp,
  TaskDetail,
  TaskSummary,
  TtsOptions,
  TtsProvider,
  TtsVoicesResp,
  UploadClipResp,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function jsonFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => b?.detail)
      .catch(() => res.statusText);
    throw new Error(`${res.status} ${detail ?? "request failed"}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => jsonFetch<HealthResp>("/api/health"),
  listTasks: () => jsonFetch<{ tasks: TaskSummary[] }>("/api/tasks"),
  getTask: (id: number) => jsonFetch<TaskDetail>(`/api/tasks/${id}`),
  deleteTask: (id: number) =>
    jsonFetch<{
      task_id: number;
      product_name: string;
      removed_images: number;
      output_removed: boolean;
      was_running: boolean;
      warning: string | null;
    }>(`/api/tasks/${id}`, { method: "DELETE" }),
  createTask: (data: FormData) =>
    jsonFetch<{ task_id: number; status: string }>("/api/tasks", {
      method: "POST",
      body: data,
    }),
  nextStep: (id: number, body: unknown) =>
    jsonFetch<{ task_id: number; next_step: string }>(
      `/api/tasks/${id}/next`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  backStep: (id: number) =>
    jsonFetch<{ task_id: number; next_step: string }>(
      `/api/tasks/${id}/back`,
      { method: "POST" },
    ),
  dropVariant: (id: number, variant_id: string) =>
    jsonFetch<{ task_id: number; dropped: string; remaining: string[] }>(
      `/api/tasks/${id}/drop-variant`,
      { method: "POST", body: JSON.stringify({ variant_id }) },
    ),
  regenerateScript: (id: number, variant_id: string, direction?: string) =>
    jsonFetch<{ task_id: number; variant_id: string; status: string }>(
      `/api/tasks/${id}/regenerate-script`,
      { method: "POST", body: JSON.stringify({ variant_id, direction }) },
    ),
  regenerateTts: (id: number, variant_id: string) =>
    jsonFetch<{ task_id: number; variant_id: string; status: string }>(
      `/api/tasks/${id}/regenerate-tts`,
      { method: "POST", body: JSON.stringify({ variant_id }) },
    ),
  regenerateClip: (
    id: number,
    variant_id: string,
    clip_num: number,
    force = false,
  ) =>
    jsonFetch<{ task_id: number; status: string }>(
      `/api/tasks/${id}/regenerate-clip`,
      { method: "POST", body: JSON.stringify({ variant_id, clip_num, force }) },
    ),
  uploadClip: async (
    id: number,
    variant_id: string,
    clip_num: number,
    file: File,
  ): Promise<UploadClipResp> => {
    const fd = new FormData();
    fd.append("variant_id", variant_id);
    fd.append("clip_num", String(clip_num));
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/tasks/${id}/upload-clip`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const detail = await res
        .json()
        .then((b) => b?.detail)
        .catch(() => res.statusText);
      throw new Error(`${res.status} ${detail ?? "upload failed"}`);
    }
    return res.json() as Promise<UploadClipResp>;
  },
  editScript: (
    id: number,
    variant_id: string,
    script_text: string,
    scene_num?: number,
  ) =>
    jsonFetch<{
      task_id: number;
      variant_id: string;
      scene_num: number | null;
      script_text_length: number;
      status: string;
    }>(`/api/tasks/${id}/edit-script`, {
      method: "PATCH",
      body: JSON.stringify({ variant_id, script_text, scene_num }),
    }),
  editPrompt: (
    id: number,
    variant_id: string,
    clip_num: number,
    i2v_prompt: string,
  ) =>
    jsonFetch<{
      task_id: number;
      variant_id: string;
      clip_num: number;
      status: string;
    }>(`/api/tasks/${id}/edit-prompt`, {
      method: "PATCH",
      body: JSON.stringify({ variant_id, clip_num, i2v_prompt }),
    }),
  buildCapcut: (
    id: number,
    template_assignments?: Record<string, string>,
    campaign_variant?: string,
  ) =>
    jsonFetch<{ task_id: number; status: string }>(
      `/api/tasks/${id}/build-capcut`,
      {
        method: "POST",
        body: JSON.stringify({ template_assignments, campaign_variant }),
      },
    ),
  getArtifact: async <T = unknown>(id: number, name: string): Promise<T> => {
    const res = await fetch(`${API_BASE}/api/tasks/${id}/artifact/${name}`, {
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${res.status} artifact ${name}`);
    return res.json() as Promise<T>;
  },
  getModelsConfig: () => jsonFetch<ModelsConfigResp>("/api/config/models"),
  listI2VModels: () =>
    jsonFetch<I2VModelsListResp>("/api/config/i2v-models"),
  listTtsVoices: (provider: TtsProvider, model = "ssfm-v30") =>
    jsonFetch<TtsVoicesResp>(
      `/api/tts/voices?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}`,
    ),
  previewTts: async (
    taskId: number,
    body: {
      provider: TtsProvider;
      options: TtsOptions;
      sample_text?: string;
      previous_text?: string;
    },
  ): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/api/tasks/${taskId}/tts-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res
        .json()
        .then((b) => b?.detail)
        .catch(() => res.statusText);
      throw new Error(`${res.status} ${detail ?? "preview failed"}`);
    }
    return res.blob();
  },
};

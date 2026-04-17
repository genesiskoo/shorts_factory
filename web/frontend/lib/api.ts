import type { HealthResp, TaskDetail, TaskSummary } from "./types";

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
  regenerateClip: (id: number, variant_id: string, clip_num: number) =>
    jsonFetch<{ task_id: number; status: string }>(
      `/api/tasks/${id}/regenerate-clip`,
      { method: "POST", body: JSON.stringify({ variant_id, clip_num }) },
    ),
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
};

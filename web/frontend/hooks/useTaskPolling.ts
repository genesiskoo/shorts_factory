"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { TaskDetail } from "@/lib/types";

/**
 * task 상태 폴링 훅.
 * - running / pending 상태는 계속 폴링
 * - awaiting_user / completed / failed 도달 시 한 번 더 fetch 후 폴링 중단
 *   (다음 action으로 transition 직후 상태 반영을 위해)
 */
export function useTaskPolling(taskId: number, intervalMs = 2000) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshTokenRef = useRef(0);

  function refresh() {
    refreshTokenRef.current += 1;
  }

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const data = await api.getTask(taskId);
        if (cancelled) return;
        setTask(data);
        setError(null);
        setLoading(false);

        const shouldPoll =
          data.status === "running" || data.status === "pending";
        if (shouldPoll) {
          timerRef.current = setTimeout(tick, intervalMs);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, intervalMs, refreshTokenRef.current]);

  return { task, error, loading, refresh };
}

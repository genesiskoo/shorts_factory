"use client";

import { useEffect, useRef } from "react";
import type { TaskDetail } from "@/lib/types";

const LONG_STEPS = new Set([
  "generating_video",
  "building_capcut",
]);

/**
 * 긴 단계(영상 생성 / CapCut 빌드) 진입 시 브라우저 Notification 권한을 요청하고,
 * 해당 단계에서 awaiting_user / completed / failed 로 전환될 때 알림을 띄운다.
 *
 * - 권한 거부 상태에서는 조용히 무시 (alert() fallback 없음)
 * - 같은 세션에서 여러 번 긴 단계를 거쳐도 각 전환마다 1번씩 발송
 * - 탭이 foreground 일 때도 발송 (브라우저 설정에 따라 OS 알림으로 노출)
 */
export function useCompletionNotification(task: TaskDetail | null) {
  const prevRef = useRef<{ step: string | null; status: string } | null>(null);

  // 긴 단계 진입 시 권한 요청 (한 번만, 유저 제스처 내에서 실행되어야 하지만
  // polling 루프 안이라 브라우저별로 무시될 수 있음 — 실패해도 무해)
  useEffect(() => {
    if (!task) return;
    if (typeof window === "undefined") return;
    if (!("Notification" in window)) return;
    if (task.status !== "running") return;
    if (!LONG_STEPS.has(task.current_step ?? "")) return;
    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }, [task?.status, task?.current_step, task]);

  // 이전 상태와 비교해 "긴 단계에서 벗어남" 순간에 알림 발송
  useEffect(() => {
    if (!task) return;
    if (typeof window === "undefined") return;

    const prev = prevRef.current;
    const curStep = task.current_step ?? null;
    const curStatus = task.status;
    prevRef.current = { step: curStep, status: curStatus };

    if (!prev) return;
    const wasLongRunning =
      prev.status === "running" && LONG_STEPS.has(prev.step ?? "");
    const finished =
      curStatus === "awaiting_user" ||
      curStatus === "completed" ||
      curStatus === "failed";
    if (!wasLongRunning || !finished) return;
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted") return;

    const title =
      curStatus === "failed"
        ? "작업 실패"
        : curStatus === "completed"
          ? "✨ 영상 제작 완료"
          : "검수 대기";
    const body =
      curStatus === "failed"
        ? `${task.product_name}: ${task.error ?? "오류"}`
        : `${task.product_name} — 다음 단계로 이동해주세요.`;

    try {
      new Notification(title, { body, tag: `task-${task.id}` });
    } catch {
      // 일부 브라우저는 secure context / user gesture 부족 시 throw
    }
  }, [task]);
}

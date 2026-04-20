"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { I2VModelInfo, TaskDetail } from "@/lib/types";

const SCRIPT_STAGES = [
  { key: "product_analyzer", label: "상품 분석" },
  { key: "pd_strategist", label: "전략 수립" },
  { key: "hook_writer", label: "훅 작성" },
  { key: "scriptwriter", label: "대본 작성" },
  { key: "script_reviewer", label: "대본 검수" },
];

const STEP_TITLES: Record<string, string> = {
  generating_script: "대본 생성 중",
  generating_tts: "TTS 생성 중",
  generating_video: "영상 생성 중",
  building_capcut: "CapCut 프로젝트 생성 중",
};

const STEP_NUMS: Record<string, number> = {
  generating_script: 2,
  select_scripts: 3,
  generating_tts: 4,
  review_tts: 5,
  review_prompts: 6,
  generating_video: 7,
  select_clips: 8,
  preview_timeline: 9,
  select_template: 10,
  building_capcut: 11,
};

// 완료 task 샘플이 쌓이기 전까지의 정적 ETA(초). 보수적 상한치 기준.
const ETA_SECONDS: Record<string, (task: TaskDetail) => number> = {
  generating_script: () => 60 * 3,
  generating_tts: (t) => Math.max(t.selected_variant_ids.length, 1) * 30,
  generating_video: (t) => {
    // variant 당 평균 3~4개 unique clip(공유 포함), 클립당 90s
    const variantCount = Math.max(t.selected_variant_ids.length, 1);
    return variantCount * 3 * 90;
  },
  building_capcut: () => 60,
};

function formatRemaining(sec: number): string {
  if (sec <= 0) return "곧 완료";
  if (sec < 60) return `약 ${sec}초`;
  const m = Math.round(sec / 60);
  return `약 ${m}분`;
}

export function StepProgress({ task }: { task: TaskDetail }) {
  const step = task.current_step ?? "";
  const title = STEP_TITLES[step] ?? "진행 중";
  const stepNum = STEP_NUMS[step] ?? 0;
  const sub = task.sub_progress;
  const message = task.progress_message ?? null;

  const [modelInfo, setModelInfo] = useState<I2VModelInfo | null>(null);
  useEffect(() => {
    if (step !== "generating_video") return;
    api
      .getModelsConfig()
      .then((r) => setModelInfo(r.i2v))
      .catch(() => {});
  }, [step]);

  const elapsed = sub ? Math.floor(sub.elapsed_sec) : 0;
  const progressPct = sub
    ? Math.round(((sub.current - 1) / Math.max(sub.total, 1)) * 100)
    : 0;

  const etaFn = ETA_SECONDS[step];
  const estimatedTotal = etaFn ? etaFn(task) : null;
  const remainingSec =
    estimatedTotal != null ? Math.max(estimatedTotal - elapsed, 0) : null;
  const etaPct =
    estimatedTotal != null
      ? Math.min(Math.round((elapsed / estimatedTotal) * 100), 95)
      : null;

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{task.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Step {stepNum}/11 · {title}
          </p>
        </div>
        <Badge>{task.status}</Badge>
      </header>

      <Card>
        <CardContent className="space-y-4 py-6">
          {step === "generating_script" && (
            <>
              <Progress value={progressPct} />
              {message && (
                <p className="rounded-md bg-muted/40 px-3 py-1.5 font-mono text-xs text-foreground/80">
                  {message}
                </p>
              )}
              <ul className="space-y-2">
                {SCRIPT_STAGES.map((stage, idx) => {
                  const currentIdx = sub
                    ? sub.agent === stage.key
                      ? sub.current - 1
                      : SCRIPT_STAGES.findIndex((s) => s.key === sub.agent)
                    : -1;
                  const state =
                    currentIdx < 0
                      ? "pending"
                      : idx < currentIdx
                        ? "done"
                        : idx === currentIdx
                          ? "running"
                          : "pending";
                  return (
                    <li
                      key={stage.key}
                      className="flex items-center gap-3 text-sm"
                    >
                      <span className="w-6 text-base">
                        {state === "done" ? "✅" : state === "running" ? "⏳" : "⏸"}
                      </span>
                      <span
                        className={
                          state === "running"
                            ? "font-semibold"
                            : state === "done"
                              ? "text-muted-foreground"
                              : "text-muted-foreground/60"
                        }
                      >
                        {stage.label}
                      </span>
                      {state === "running" && (
                        <span className="text-xs text-muted-foreground">
                          ({elapsed}s 경과)
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {step === "generating_tts" && (
            <>
              <Progress value={etaPct ?? 50} />
              <p className="text-sm text-muted-foreground">
                선택된 {task.selected_variant_ids.length}개 variant의 TTS를
                생성하고 있습니다.
              </p>
              <EtaRow
                elapsed={elapsed}
                remainingSec={remainingSec}
                agent={sub?.agent}
                message={message}
              />
            </>
          )}

          {step === "generating_video" && (
            <>
              <Progress value={etaPct ?? 30} />
              {modelInfo && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs">
                  <Badge variant="outline">{modelInfo.family}</Badge>
                  <span className="font-semibold">{modelInfo.label}</span>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                    {modelInfo.model}
                  </code>
                  <span className="text-muted-foreground">
                    · 클립당 약 {modelInfo.expected_sec_per_clip}초
                  </span>
                </div>
              )}
              <p className="text-sm text-muted-foreground">
                이미지→영상 클립을 생성 중입니다. 브라우저 알림을 허용하시면
                완료 시 알려드립니다.
              </p>
              <EtaRow
                elapsed={elapsed}
                remainingSec={remainingSec}
                agent={sub?.agent}
                message={message}
              />
              <VideoSkeletonPreview task={task} />
              <div className="flex justify-end pt-2">
                <Button asChild variant="outline" size="sm">
                  <Link href="/">백그라운드로 돌리고 홈으로 →</Link>
                </Button>
              </div>
            </>
          )}

          {step === "building_capcut" && (
            <>
              <Progress value={etaPct ?? 80} />
              <p className="text-sm text-muted-foreground">
                CapCut 프로젝트 파일을 생성하고 있습니다.
              </p>
              <EtaRow
                elapsed={elapsed}
                remainingSec={remainingSec}
                agent={sub?.agent}
                message={message}
              />
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

function EtaRow({
  elapsed,
  remainingSec,
  agent,
  message,
}: {
  elapsed: number;
  remainingSec: number | null;
  agent: string | null | undefined;
  message?: string | null;
}) {
  const eta = (
    <div className="flex items-center justify-between text-xs text-muted-foreground">
      <span>
        {agent ? `${agent} · ` : ""}
        {elapsed}s 경과
      </span>
      {remainingSec != null && (
        <span className="rounded-md bg-muted/60 px-2 py-0.5">
          예상 남은 시간: {formatRemaining(remainingSec)}
        </span>
      )}
    </div>
  );
  if (!message) return eta;
  return (
    <div className="space-y-1.5">
      <p className="rounded-md bg-muted/40 px-3 py-1.5 font-mono text-xs text-foreground/80">
        {message}
      </p>
      {eta}
    </div>
  );
}

function VideoSkeletonPreview({ task }: { task: TaskDetail }) {
  const variants = task.selected_variant_ids;
  if (variants.length === 0) return null;
  return (
    <div className="space-y-3 pt-2">
      <div className="text-xs font-medium text-muted-foreground">
        생성 예정 클립 미리보기
      </div>
      <div className="space-y-2">
        {variants.map((vid) => (
          <div key={vid} className="rounded-md border p-2">
            <div className="mb-2 flex items-center gap-2 text-xs">
              <Badge variant="outline">{vid}</Badge>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton
                  key={i}
                  className="aspect-[9/16] w-full"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

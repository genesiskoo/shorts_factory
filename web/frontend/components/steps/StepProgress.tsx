"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import type { TaskDetail } from "@/lib/types";

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

export function StepProgress({ task }: { task: TaskDetail }) {
  const step = task.current_step ?? "";
  const title = STEP_TITLES[step] ?? "진행 중";
  const stepNum = STEP_NUMS[step] ?? 0;
  const sub = task.sub_progress;

  const elapsed = sub ? Math.floor(sub.elapsed_sec) : 0;
  const progressPct = sub
    ? Math.round(((sub.current - 1) / Math.max(sub.total, 1)) * 100)
    : 0;

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
              <Progress value={50} className="animate-pulse" />
              <p className="text-sm text-muted-foreground">
                선택된 variant의 TTS를 생성하고 있습니다. 약 30초~1분 소요.
              </p>
              {sub && (
                <p className="text-xs text-muted-foreground">
                  {sub.agent} · {elapsed}s 경과
                </p>
              )}
            </>
          )}

          {step === "generating_video" && (
            <>
              <Progress value={30} className="animate-pulse" />
              <p className="text-sm text-muted-foreground">
                Veo로 영상 클립을 생성 중입니다. 클립 1개당 약 60~120초 소요.
                전체 완료까지 5~15분 걸릴 수 있습니다.
              </p>
              {sub && (
                <p className="text-xs text-muted-foreground">
                  {sub.agent} · {elapsed}s 경과
                </p>
              )}
              <div className="flex justify-end pt-2">
                <Button asChild variant="outline" size="sm">
                  <Link href="/">백그라운드로 돌리고 홈으로 →</Link>
                </Button>
              </div>
            </>
          )}

          {step === "building_capcut" && (
            <>
              <Progress value={80} className="animate-pulse" />
              <p className="text-sm text-muted-foreground">
                CapCut 프로젝트 파일을 생성하고 있습니다.
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

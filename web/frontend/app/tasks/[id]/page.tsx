"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTaskPolling } from "@/hooks/useTaskPolling";
import { useCompletionNotification } from "@/hooks/useCompletionNotification";
import { StepProgress } from "@/components/steps/StepProgress";
import { SelectScripts } from "@/components/steps/SelectScripts";
import { SelectTts } from "@/components/steps/SelectTts";
import { ReviewTts } from "@/components/steps/ReviewTts";
import { PromptReview } from "@/components/steps/PromptReview";
import { SelectClips } from "@/components/steps/SelectClips";
import { TimelinePreview } from "@/components/steps/TimelinePreview";
import { SelectTemplate } from "@/components/steps/SelectTemplate";
import { Complete } from "@/components/steps/Complete";
import type { TaskDetail } from "@/lib/types";

export default function TaskPage() {
  const params = useParams<{ id: string }>();
  const taskId = Number(params?.id);

  const { task, error, loading, refresh } = useTaskPolling(taskId);
  useCompletionNotification(task);

  if (Number.isNaN(taskId)) {
    return <ErrorView message="잘못된 task_id" />;
  }
  if (loading) {
    return (
      <main className="mx-auto max-w-2xl p-8 text-sm text-muted-foreground">
        불러오는 중…
      </main>
    );
  }
  if (error) return <ErrorView message={error} />;
  if (!task) return <ErrorView message="작업을 찾을 수 없습니다." />;

  if (task.status === "failed") return <FailedView task={task} />;
  if (task.status === "completed") return <Complete task={task} />;

  switch (task.current_step) {
    case "generating_script":
    case "generating_tts":
    case "generating_video":
    case "building_capcut":
      return <StepProgress task={task} />;
    case "select_scripts":
      return <SelectScripts task={task} onChange={refresh} />;
    case "select_tts":
      return <SelectTts task={task} onChange={refresh} />;
    case "review_tts":
      return <ReviewTts task={task} onChange={refresh} />;
    case "review_prompts":
      return <PromptReview task={task} onChange={refresh} />;
    case "select_clips":
      return <SelectClips task={task} onChange={refresh} />;
    case "preview_timeline":
      return <TimelinePreview task={task} onChange={refresh} />;
    case "select_template":
      return <SelectTemplate task={task} onChange={refresh} />;
    default:
      return <NotYetImplemented task={task} />;
  }
}

function ErrorView({ message }: { message: string }) {
  return (
    <main className="mx-auto max-w-2xl p-8 space-y-4">
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">오류</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {message}
          <div className="mt-4">
            <Button asChild variant="outline" size="sm">
              <Link href="/">← 홈</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

function FailedView({ task }: { task: TaskDetail }) {
  return (
    <main className="mx-auto max-w-2xl p-8 space-y-4">
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">작업 실패</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>
            <span className="text-muted-foreground">상품: </span>
            {task.product_name}
          </div>
          <div>
            <span className="text-muted-foreground">단계: </span>
            {task.current_step ?? "-"}
          </div>
          {task.error && (
            <div className="rounded-md bg-destructive/10 p-3 font-mono text-xs text-destructive">
              {task.error}
            </div>
          )}
          <div className="pt-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/">← 홈</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

function NotYetImplemented({ task }: { task: TaskDetail }) {
  return (
    <main className="mx-auto max-w-2xl p-8 space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{task.product_name}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <div>
            현재 단계:{" "}
            <code className="rounded bg-muted px-2 py-0.5 text-xs">
              {task.current_step ?? "-"}
            </code>
          </div>
          <div>
            상태:{" "}
            <code className="rounded bg-muted px-2 py-0.5 text-xs">
              {task.status}
            </code>
          </div>
          <p className="pt-2">
            이 단계 UI는 Day 5~6에 추가됩니다.
          </p>
          <div className="pt-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/">← 홈</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

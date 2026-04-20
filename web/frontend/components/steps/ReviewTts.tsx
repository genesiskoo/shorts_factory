"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { DropVariantButton } from "@/components/DropVariantButton";
import { API_BASE, api } from "@/lib/api";
import type {
  ScriptEntry,
  ScriptsFinalJson,
  TaskDetail,
} from "@/lib/types";

export function ReviewTts({
  task,
  onChange,
}: {
  task: TaskDetail;
  onChange: () => void;
}) {
  const [scripts, setScripts] = useState<ScriptsFinalJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [regenId, setRegenId] = useState<string | null>(null);
  const [cacheBust, setCacheBust] = useState(0);

  const load = useCallback(async () => {
    try {
      const sc = await api.getArtifact<ScriptsFinalJson>(task.id, "scripts_final");
      setScripts(sc);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [task.id]);

  useEffect(() => {
    load();
  }, [load]);

  // tts_generator/typecast_tts bg task 진행 중인지 감지. 완료 전이에 cacheBust 증가.
  const busyWithRegen =
    task.status === "running" &&
    (task.sub_progress?.agent === "tts_generator" ||
      task.sub_progress?.agent === "typecast_tts");
  const prevBusyRef = useRef(busyWithRegen);
  useEffect(() => {
    if (prevBusyRef.current && !busyWithRegen) {
      setCacheBust((c) => c + 1);
      setRegenId(null);
      load();
    }
    prevBusyRef.current = busyWithRegen;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busyWithRegen]);

  const selected = new Set(task.selected_variant_ids);
  const rows: ScriptEntry[] = (scripts?.scripts ?? []).filter((s) =>
    selected.has(s.variant_id),
  );

  async function regenerate(vid: string) {
    setRegenId(vid);
    try {
      await api.regenerateTts(task.id, vid);
      onChange();
      // regenId는 bg task 완료 시 위 useEffect에서 해제 (Veo/TTS 실제 처리 시간
      // 동안 spinner 유지).
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setRegenId(null);
    }
  }

  async function next() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, { step: "review_tts" });
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <Card className="border-destructive/40">
          <CardContent className="py-6 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      </main>
    );
  }
  if (!scripts) {
    return (
      <main className="mx-auto max-w-3xl p-8 text-sm text-muted-foreground">
        불러오는 중…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold">{task.product_name}</h1>
        <p className="text-sm text-muted-foreground">
          Step 5/11 · TTS 검수 · {rows.length}개 variant
        </p>
      </header>

      {busyWithRegen && (
        <Card className="border-blue-500/40 bg-blue-50/60 dark:bg-blue-950/30">
          <CardContent className="flex items-center gap-2 py-3 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>
              TTS 재생성 중 — 완료되면 자동으로 새 오디오가 로드됩니다.
            </span>
          </CardContent>
        </Card>
      )}

      {rows.length === 1 ? (
        <TtsCard
          entry={rows[0]}
          taskId={task.id}
          regenerating={regenId === rows[0].variant_id}
          disabled={regenId !== null || task.status === "running"}
          onRegenerate={() => regenerate(rows[0].variant_id)}
          remainingCount={rows.length}
          onDropped={onChange}
          cacheBust={cacheBust}
        />
      ) : rows.length > 1 ? (
        <Tabs defaultValue={rows[0].variant_id} className="w-full">
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 p-1">
            {rows.map((s) => (
              <TabsTrigger
                key={s.variant_id}
                value={s.variant_id}
                className="data-[state=active]:font-semibold"
              >
                {s.variant_id}
                {s.script_text && (
                  <span className="ml-1.5 text-[10px] text-muted-foreground">
                    {s.script_text.length}자
                  </span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
          {rows.map((s) => (
            <TabsContent key={s.variant_id} value={s.variant_id}>
              <TtsCard
                entry={s}
                taskId={task.id}
                regenerating={regenId === s.variant_id}
                disabled={regenId !== null || task.status === "running"}
                onRegenerate={() => regenerate(s.variant_id)}
                remainingCount={rows.length}
                onDropped={onChange}
                cacheBust={cacheBust}
              />
            </TabsContent>
          ))}
        </Tabs>
      ) : null}

      <div className="flex justify-end">
        <Button
          size="lg"
          onClick={next}
          disabled={submitting || task.status === "running"}
        >
          영상 프롬프트 확인 →
        </Button>
      </div>
    </main>
  );
}

function TtsCard({
  entry,
  taskId,
  regenerating,
  disabled,
  onRegenerate,
  remainingCount,
  onDropped,
  cacheBust,
}: {
  entry: ScriptEntry;
  taskId: number;
  regenerating: boolean;
  disabled: boolean;
  onRegenerate: () => void;
  remainingCount: number;
  onDropped: () => void;
  cacheBust: number;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-4">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{entry.variant_id}</span>
          {entry.script_text && (
            <Badge variant="secondary">{entry.script_text.length}자</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={onRegenerate}
          disabled={disabled}
          className="border-amber-500/60 text-amber-700 hover:bg-amber-50 hover:text-amber-800"
        >
          {regenerating ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              재생성 중…
            </>
          ) : (
            "🔄 재생성"
          )}
        </Button>
        <DropVariantButton
          taskId={taskId}
          variantId={entry.variant_id}
          remainingCount={remainingCount}
          onDropped={onDropped}
          disabled={disabled}
        />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {entry.script_text && (
          <div className="whitespace-pre-wrap rounded-md bg-muted/40 p-3">
            {entry.script_text}
          </div>
        )}
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio
          controls
          preload="metadata"
          className="w-full"
          src={`${API_BASE}/api/tasks/${taskId}/audio/${entry.variant_id}?v=${cacheBust}`}
        />
      </CardContent>
    </Card>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { toast } from "sonner";
import { DropVariantButton } from "@/components/DropVariantButton";
import { API_BASE, api } from "@/lib/api";
import type { StrategyJson, StrategyVariant, TaskDetail } from "@/lib/types";

const CLIP_DURATION_SEC = 6;

export function TimelinePreview({
  task,
  onChange,
}: {
  task: TaskDetail;
  onChange: () => void;
}) {
  const [strategy, setStrategy] = useState<StrategyJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      setStrategy(await api.getArtifact<StrategyJson>(task.id, "strategy"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [task.id]);

  useEffect(() => {
    load();
  }, [load]);

  const variants: StrategyVariant[] = useMemo(() => {
    const selected = new Set(task.selected_variant_ids);
    return (strategy?.variants ?? []).filter((v) => selected.has(v.variant_id));
  }, [strategy, task.selected_variant_ids]);

  async function next() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, { step: "preview_timeline" });
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-4xl p-8">
        <Card className="border-destructive/40">
          <CardContent className="py-6 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      </main>
    );
  }
  if (!strategy) {
    return (
      <main className="mx-auto max-w-4xl p-8 text-sm text-muted-foreground">
        불러오는 중…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{task.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Step 9/11 · 타임라인 프리뷰
          </p>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">← 홈</Link>
        </Button>
      </header>

      <Card className="border-blue-500/40 bg-blue-50/50 dark:bg-blue-950/20">
        <CardContent className="py-3 text-xs text-muted-foreground">
          클라이언트 사이드 동기 재생 (대략적 프리뷰). 실제 CapCut 렌더 결과와
          트랜지션·자막·효과가 다를 수 있습니다.
        </CardContent>
      </Card>

      {variants.length === 1 ? (
        <VariantPreview
          task={task}
          variant={variants[0]}
          remainingCount={variants.length}
          onDropped={onChange}
          dropDisabled={submitting || task.status === "running"}
        />
      ) : variants.length > 1 ? (
        <Tabs defaultValue={variants[0].variant_id} className="w-full">
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 p-1">
            {variants.map((v) => (
              <TabsTrigger
                key={v.variant_id}
                value={v.variant_id}
                className="data-[state=active]:font-semibold"
              >
                {v.variant_id}
              </TabsTrigger>
            ))}
          </TabsList>
          {variants.map((v) => (
            <TabsContent key={v.variant_id} value={v.variant_id}>
              <VariantPreview
                task={task}
                variant={v}
                remainingCount={variants.length}
                onDropped={onChange}
                dropDisabled={submitting || task.status === "running"}
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
          CapCut 템플릿 선택 →
        </Button>
      </div>
    </main>
  );
}

function VariantPreview({
  task,
  variant,
  remainingCount,
  onDropped,
  dropDisabled,
}: {
  task: TaskDetail;
  variant: StrategyVariant;
  remainingCount: number;
  onDropped: () => void;
  dropDisabled: boolean;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [playing, setPlaying] = useState(false);

  // selected clip_nums, fallback to all
  const selectedNums = useMemo(() => {
    const stored = task.selected_clips?.[variant.variant_id];
    if (stored && stored.length > 0) return stored;
    return (variant.clips ?? []).map((c) => c.clip_num);
  }, [task.selected_clips, variant.clips, variant.variant_id]);

  const clips = useMemo(
    () =>
      (variant.clips ?? [])
        .filter((c) => selectedNums.includes(c.clip_num))
        .sort((a, b) => a.clip_num - b.clip_num),
    [variant.clips, selectedNums],
  );

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const handler = () => {
      const idx = Math.min(
        Math.floor(a.currentTime / CLIP_DURATION_SEC),
        clips.length - 1,
      );
      setActiveIdx(idx);
    };
    a.addEventListener("timeupdate", handler);
    return () => a.removeEventListener("timeupdate", handler);
  }, [clips.length]);

  useEffect(() => {
    videoRefs.current.forEach((v, i) => {
      if (!v) return;
      if (i === activeIdx && playing) {
        v.currentTime = 0;
        v.play().catch(() => {});
      } else {
        v.pause();
      }
    });
  }, [activeIdx, playing]);

  async function togglePlay() {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) {
      await a.play().catch(() => {});
      setPlaying(true);
    } else {
      a.pause();
      setPlaying(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{variant.variant_id}</span>
          <Badge variant="outline">{clips.length}개 클립</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={togglePlay}>
            {playing ? "⏸ 일시정지" : "▶ 재생"}
          </Button>
          <DropVariantButton
            taskId={task.id}
            variantId={variant.variant_id}
            remainingCount={remainingCount}
            onDropped={onDropped}
            disabled={dropDisabled}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2" style={{
          gridTemplateColumns: `repeat(${Math.max(clips.length, 1)}, minmax(0, 1fr))`,
        }}>
          {clips.map((c, i) => (
            <div
              key={c.clip_num}
              className={`overflow-hidden rounded border transition ${
                i === activeIdx && playing
                  ? "ring-2 ring-primary"
                  : "opacity-60"
              }`}
            >
              <video
                ref={(el) => {
                  videoRefs.current[i] = el;
                }}
                muted
                preload="metadata"
                className="aspect-[9/16] w-full bg-black object-cover"
                src={`${API_BASE}/api/tasks/${task.id}/clip/${variant.variant_id}/${c.clip_num}`}
              />
              <div className="bg-muted/50 py-0.5 text-center text-[10px]">
                #{c.clip_num} · {i * CLIP_DURATION_SEC}s~
                {(i + 1) * CLIP_DURATION_SEC}s
              </div>
            </div>
          ))}
        </div>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio
          ref={audioRef}
          controls
          preload="metadata"
          className="w-full"
          src={`${API_BASE}/api/tasks/${task.id}/audio/${variant.variant_id}`}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
        />
      </CardContent>
    </Card>
  );
}

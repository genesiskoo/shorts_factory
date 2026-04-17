"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { API_BASE, api } from "@/lib/api";
import type { StrategyJson, StrategyVariant, TaskDetail } from "@/lib/types";

const MIN_CLIPS_PER_VARIANT = 3;

export function SelectClips({
  task,
  onChange,
}: {
  task: TaskDetail;
  onChange: () => void;
}) {
  const [strategy, setStrategy] = useState<StrategyJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [regenKey, setRegenKey] = useState<string | null>(null);
  // variant_id -> set of selected clip_nums
  const [selection, setSelection] = useState<Record<string, Set<number>>>({});

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

  // 기본값: 모든 클립 선택. task.selected_clips가 있으면 우선 사용.
  useEffect(() => {
    if (!strategy) return;
    const selected = new Set(task.selected_variant_ids);
    const next: Record<string, Set<number>> = {};
    for (const v of strategy.variants ?? []) {
      if (!selected.has(v.variant_id)) continue;
      const stored = task.selected_clips?.[v.variant_id];
      const defaults = (v.clips ?? []).map((c) => c.clip_num);
      next[v.variant_id] = new Set(
        stored && stored.length > 0 ? stored : defaults,
      );
    }
    setSelection(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy?.variants, task.selected_variant_ids]);

  const variants: StrategyVariant[] = useMemo(() => {
    const selected = new Set(task.selected_variant_ids);
    return (strategy?.variants ?? []).filter((v) => selected.has(v.variant_id));
  }, [strategy, task.selected_variant_ids]);

  function toggle(vid: string, num: number) {
    setSelection((prev) => {
      const curr = new Set(prev[vid] ?? []);
      if (curr.has(num)) curr.delete(num);
      else curr.add(num);
      return { ...prev, [vid]: curr };
    });
  }

  const violations = variants.filter(
    (v) => (selection[v.variant_id]?.size ?? 0) < MIN_CLIPS_PER_VARIANT,
  );

  async function regenerate(vid: string, num: number) {
    const key = `${vid}-${num}`;
    setRegenKey(key);
    try {
      await api.regenerateClip(task.id, vid, num);
      onChange();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setRegenKey(null);
    }
  }

  async function next() {
    if (violations.length > 0) return;
    setSubmitting(true);
    try {
      const selectedClips: Record<string, number[]> = {};
      for (const [vid, s] of Object.entries(selection)) {
        selectedClips[vid] = Array.from(s).sort((a, b) => a - b);
      }
      await api.nextStep(task.id, {
        step: "select_clips",
        selected_clips: selectedClips,
      });
      onChange();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
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
    <main className="mx-auto max-w-5xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold">{task.product_name}</h1>
        <p className="text-sm text-muted-foreground">
          Step 8/11 · 클립 선택 · variant당 최소 {MIN_CLIPS_PER_VARIANT}개 유지
        </p>
      </header>

      {violations.length > 0 && (
        <Card className="border-amber-500/40 bg-amber-50/50 dark:bg-amber-950/20">
          <CardContent className="py-3 text-sm">
            다음 variant는 최소 클립 수({MIN_CLIPS_PER_VARIANT}개) 미달:{" "}
            <strong>{violations.map((v) => v.variant_id).join(", ")}</strong>
          </CardContent>
        </Card>
      )}

      <div className="space-y-6">
        {variants.map((v) => {
          const count = selection[v.variant_id]?.size ?? 0;
          return (
            <Card key={v.variant_id}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 py-4">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{v.variant_id}</span>
                  <Badge
                    variant={
                      count >= MIN_CLIPS_PER_VARIANT
                        ? "secondary"
                        : "destructive"
                    }
                  >
                    {count}/{v.clips?.length ?? 0}개 선택
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {(v.clips ?? []).map((c) => {
                    const selected = selection[v.variant_id]?.has(c.clip_num);
                    const rk = `${v.variant_id}-${c.clip_num}`;
                    return (
                      <div
                        key={c.clip_num}
                        className={`rounded-md border p-2 ${selected ? "" : "opacity-50"}`}
                      >
                        <video
                          controls
                          preload="metadata"
                          className="aspect-[9/16] w-full rounded bg-black object-cover"
                          src={`${API_BASE}/api/tasks/${task.id}/clip/${v.variant_id}/${c.clip_num}`}
                        />
                        <div className="mt-1 flex items-center justify-between text-xs">
                          <label className="flex items-center gap-1">
                            <Checkbox
                              checked={!!selected}
                              onCheckedChange={() =>
                                toggle(v.variant_id, c.clip_num)
                              }
                            />
                            <span>#{c.clip_num}</span>
                          </label>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs"
                            onClick={() => regenerate(v.variant_id, c.clip_num)}
                            disabled={
                              regenKey !== null || task.status === "running"
                            }
                          >
                            {regenKey === rk ? "…" : "🔄"}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="flex justify-end">
        <Button
          size="lg"
          onClick={next}
          disabled={
            submitting || violations.length > 0 || task.status === "running"
          }
        >
          타임라인 프리뷰 →
        </Button>
      </div>
    </main>
  );
}

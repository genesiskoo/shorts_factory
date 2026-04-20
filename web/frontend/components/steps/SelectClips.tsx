"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  ClipSourceEntry,
  StrategyJson,
  StrategyVariant,
  TaskDetail,
} from "@/lib/types";

// video_generator는 실제 Veo 호출까지 30~60초. bg task가 sub_agent로 표시됨.
const REGEN_SUB_AGENTS = new Set(["video_generator"]);

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
  const [uploadKey, setUploadKey] = useState<string | null>(null);
  const [cacheBust, setCacheBust] = useState(0);
  // variant_id -> set of selected clip_nums
  const [selection, setSelection] = useState<Record<string, Set<number>>>({});
  // user clip 위에 재생성 confirm
  const [overwriteTarget, setOverwriteTarget] = useState<
    { vid: string; num: number } | null
  >(null);

  const clipSources = task.clip_sources ?? {};
  const sourceOf = (vid: string, num: number): ClipSourceEntry | undefined =>
    clipSources[`${vid}_${num}`];

  const busyWithRegen =
    task.status === "running" &&
    !!task.sub_progress?.agent &&
    REGEN_SUB_AGENTS.has(task.sub_progress.agent);
  const prevBusyRef = useRef(busyWithRegen);

  // video_generator bg task 완료 감지 → cacheBust 증가 + regenKey 해제.
  // 이렇게 해야 spinner가 bg task 내내 유지되고, 새 mp4가 브라우저에 즉시 로드됨.
  useEffect(() => {
    if (prevBusyRef.current && !busyWithRegen) {
      setCacheBust((c) => c + 1);
      setRegenKey(null);
      load();
    }
    prevBusyRef.current = busyWithRegen;
    // load는 의존성에서 제외(무한루프 방지) — busyWithRegen 전이 시에만 부르고 싶음
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busyWithRegen]);

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

  async function regenerate(vid: string, num: number, force = false) {
    const key = `${vid}-${num}`;
    setRegenKey(key);
    try {
      await api.regenerateClip(task.id, vid, num, force);
      onChange();
      // regenKey는 bg task 완료 시 위 useEffect에서 해제. POST 반환 직후 해제하면
      // Veo 호출 30~60초 동안 spinner가 사라져 "무반응"처럼 보이는 버그(해결).
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setRegenKey(null);
    }
  }

  function onRegenClick(vid: string, num: number) {
    if (sourceOf(vid, num)?.source === "user") {
      setOverwriteTarget({ vid, num });
      return;
    }
    regenerate(vid, num, false);
  }

  async function uploadClip(vid: string, num: number, file: File) {
    const key = `${vid}-${num}`;
    setUploadKey(key);
    try {
      const r = await api.uploadClip(task.id, vid, num, file);
      if (r.aspect_ratio_warning) {
        toast.warning(r.aspect_ratio_warning);
      } else if (r.ffprobe_skipped) {
        toast.info("ffprobe 미설치 — 비율/길이 검증 스킵 (CapCut에서 확인)");
      } else {
        toast.success(
          `업로드 완료 (${r.duration_sec?.toFixed(1)}s · ${r.width}×${r.height})`,
        );
      }
      setCacheBust((c) => c + 1);
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploadKey(null);
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

      {busyWithRegen && (
        <Card className="border-blue-500/40 bg-blue-50/60 dark:bg-blue-950/30">
          <CardContent className="flex items-center gap-2 py-3 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>
              클립 재생성 중 — Veo 호출은 30~60초 소요됩니다. 완료되면 자동으로
              새 영상이 표시됩니다.
            </span>
          </CardContent>
        </Card>
      )}

      {variants.length > 0 && (
        <Tabs defaultValue={variants[0].variant_id} className="w-full">
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 p-1">
            {variants.map((v) => {
              const count = selection[v.variant_id]?.size ?? 0;
              const ok = count >= MIN_CLIPS_PER_VARIANT;
              return (
                <TabsTrigger
                  key={v.variant_id}
                  value={v.variant_id}
                  className="gap-1.5 data-[state=active]:font-semibold"
                >
                  <span
                    className={
                      ok ? "text-primary" : "text-destructive"
                    }
                    aria-hidden
                  >
                    {ok ? "✓" : "!"}
                  </span>
                  {v.variant_id}
                  <span className="ml-1 text-[10px] text-muted-foreground">
                    {count}/{v.clips?.length ?? 0}
                  </span>
                </TabsTrigger>
              );
            })}
          </TabsList>
          {variants.map((v) => {
            const count = selection[v.variant_id]?.size ?? 0;
            return (
              <TabsContent key={v.variant_id} value={v.variant_id}>
                <Card>
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
                    <DropVariantButton
                      taskId={task.id}
                      variantId={v.variant_id}
                      remainingCount={variants.length}
                      onDropped={onChange}
                      disabled={
                        submitting ||
                        regenKey !== null ||
                        task.status === "running"
                      }
                    />
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      {(v.clips ?? []).map((c) => {
                        const selected = selection[v.variant_id]?.has(
                          c.clip_num,
                        );
                        const rk = `${v.variant_id}-${c.clip_num}`;
                        const src = sourceOf(v.variant_id, c.clip_num);
                        const isUserClip = src?.source === "user";
                        const busy =
                          regenKey !== null ||
                          uploadKey !== null ||
                          task.status === "running";
                        return (
                          <div
                            key={c.clip_num}
                            className={`relative rounded-md border p-2 ${selected ? "" : "opacity-50"} ${isUserClip ? "border-emerald-500/60" : ""}`}
                          >
                            {isUserClip && (
                              <Badge
                                variant="secondary"
                                className="absolute right-2 top-2 z-10 bg-emerald-600 text-[10px] text-white"
                              >
                                내 클립
                              </Badge>
                            )}
                            <video
                              controls
                              preload="metadata"
                              className="aspect-[9/16] w-full rounded bg-black object-cover"
                              src={`${API_BASE}/api/tasks/${task.id}/clip/${v.variant_id}/${c.clip_num}?v=${cacheBust}`}
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
                              <div className="flex items-center gap-1">
                                <label
                                  className="cursor-pointer rounded px-1.5 py-0.5 text-emerald-700 hover:bg-emerald-50"
                                  aria-label={`clip ${c.clip_num} 사용자 mp4 업로드`}
                                  title="내 mp4 업로드"
                                >
                                  {uploadKey === rk ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    "📤"
                                  )}
                                  <input
                                    type="file"
                                    accept="video/mp4"
                                    className="hidden"
                                    disabled={busy}
                                    onChange={(e) => {
                                      const f = e.target.files?.[0];
                                      e.target.value = "";
                                      if (f) {
                                        uploadClip(
                                          v.variant_id,
                                          c.clip_num,
                                          f,
                                        );
                                      }
                                    }}
                                  />
                                </label>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-6 px-2 text-xs text-amber-600 hover:bg-amber-50 hover:text-amber-700"
                                  onClick={() =>
                                    onRegenClick(v.variant_id, c.clip_num)
                                  }
                                  disabled={busy}
                                  aria-label={`clip ${c.clip_num} Veo 재생성`}
                                >
                                  {regenKey === rk ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    "🔄"
                                  )}
                                </Button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>
            );
          })}
        </Tabs>
      )}

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

      <Dialog
        open={!!overwriteTarget}
        onOpenChange={(o) => !o && setOverwriteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>업로드한 클립을 덮어쓸까요?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {overwriteTarget?.vid} #{overwriteTarget?.num}는 사용자가 업로드한
            mp4입니다. Veo로 재생성하면 업로드 파일이 삭제됩니다.
          </p>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setOverwriteTarget(null)}
            >
              취소
            </Button>
            <Button
              className="bg-amber-600 text-white hover:bg-amber-700"
              onClick={() => {
                if (overwriteTarget) {
                  regenerate(overwriteTarget.vid, overwriteTarget.num, true);
                  setOverwriteTarget(null);
                }
              }}
            >
              덮어쓰고 재생성
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

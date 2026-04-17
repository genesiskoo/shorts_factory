"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { API_BASE, api } from "@/lib/api";
import type { StrategyJson, StrategyVariant, TaskDetail } from "@/lib/types";

export function PromptReview({
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

  const selected = new Set(task.selected_variant_ids);
  const variants: StrategyVariant[] = (strategy?.variants ?? []).filter((v) =>
    selected.has(v.variant_id),
  );

  // img_N → filename 매핑
  const imageByKey = useMemo(() => {
    const m: Record<string, string> = {};
    task.images.forEach((p, i) => {
      const basename = p.split(/[\\/]/).pop() ?? p;
      m[`img_${i + 1}`] = basename;
    });
    return m;
  }, [task.images]);

  const totalClips = variants.reduce(
    (sum, v) => sum + (v.clips?.length ?? 0),
    0,
  );
  const estSec = totalClips * 90;
  const estMin = Math.round(estSec / 60);

  async function startVideo() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, { step: "review_prompts" });
      onChange();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
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
  if (!strategy) {
    return (
      <main className="mx-auto max-w-3xl p-8 text-sm text-muted-foreground">
        불러오는 중…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold">{task.product_name}</h1>
        <p className="text-sm text-muted-foreground">
          Step 6/11 · 영상 프롬프트 확인
        </p>
      </header>

      <Card className="border-amber-500/40 bg-amber-50/50 dark:bg-amber-950/20">
        <CardContent className="py-4 text-sm">
          <ul className="space-y-1">
            <li>
              ⚠️ 총 {totalClips}개 클립 생성 예정 · 클립당 약 60~120초 소요
            </li>
            <li>
              ⚠️ Veo 3.1 preview 크레딧 차감 · 일일 쿼터 약 7클립 제한
            </li>
            <li>⚠️ 예상 총 소요 시간: 약 {estMin}분</li>
          </ul>
        </CardContent>
      </Card>

      <div className="space-y-4">
        {variants.map((v) => (
          <Card key={v.variant_id}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 py-4">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{v.variant_id}</span>
                <Badge variant="outline">{v.clips?.length ?? 0}개 클립</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {(v.clips ?? []).map((c) => {
                const basename = imageByKey[c.source_image];
                const thumb = basename
                  ? `${API_BASE}/api/tasks/${task.id}/image/${encodeURIComponent(basename)}`
                  : null;
                return (
                  <div
                    key={c.clip_num}
                    className="flex gap-3 rounded-md border p-2"
                  >
                    {thumb && (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img
                        src={thumb}
                        alt={c.source_image}
                        className="h-20 w-20 flex-shrink-0 rounded object-cover"
                      />
                    )}
                    <div className="min-w-0 flex-1 space-y-1 text-sm">
                      <div className="flex items-center gap-2 text-xs">
                        <Badge variant="secondary">Clip {c.clip_num}</Badge>
                        <Badge variant="outline">{c.source_image}</Badge>
                        {c.timeline && <Badge>{c.timeline}</Badge>}
                      </div>
                      <p className="text-muted-foreground">{c.i2v_prompt}</p>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex justify-end gap-2">
        <Button asChild variant="ghost">
          <Link href={`/tasks/${task.id}`}>← 이전</Link>
        </Button>
        <Button
          size="lg"
          onClick={startVideo}
          disabled={submitting || task.status === "running"}
        >
          Veo로 영상 생성 시작 →
        </Button>
      </div>
    </main>
  );
}

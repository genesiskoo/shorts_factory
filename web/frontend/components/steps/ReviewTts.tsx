"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

  const selected = new Set(task.selected_variant_ids);
  const rows: ScriptEntry[] = (scripts?.scripts ?? []).filter((s) =>
    selected.has(s.variant_id),
  );

  async function regenerate(vid: string) {
    setRegenId(vid);
    try {
      await api.regenerateTts(task.id, vid);
      onChange();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setRegenId(null);
    }
  }

  async function next() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, { step: "review_tts" });
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

      <div className="space-y-3">
        {rows.map((s) => (
          <Card key={s.variant_id}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 py-4">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{s.variant_id}</span>
                {s.script_text && (
                  <Badge variant="secondary">{s.script_text.length}자</Badge>
                )}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => regenerate(s.variant_id)}
                disabled={regenId !== null || task.status === "running"}
              >
                {regenId === s.variant_id ? "재생성 중…" : "🔄 재생성"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {s.script_text && (
                <div className="whitespace-pre-wrap rounded-md bg-muted/40 p-3">
                  {s.script_text}
                </div>
              )}
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <audio
                controls
                preload="metadata"
                className="w-full"
                src={`${API_BASE}/api/tasks/${task.id}/audio/${s.variant_id}`}
              />
            </CardContent>
          </Card>
        ))}
      </div>

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

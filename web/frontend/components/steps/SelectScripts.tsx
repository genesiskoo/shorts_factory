"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type {
  ScriptEntry,
  ScriptsFinalJson,
  StrategyJson,
  StrategyVariant,
  TaskDetail,
} from "@/lib/types";

interface Props {
  task: TaskDetail;
  onChange: () => void; // 재생성 등 action 후 polling re-trigger
}

export function SelectScripts({ task, onChange }: Props) {
  const router = useRouter();
  const [strategy, setStrategy] = useState<StrategyJson | null>(null);
  const [scripts, setScripts] = useState<ScriptsFinalJson | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [regenTarget, setRegenTarget] = useState<string | null>(null);
  const [regenDir, setRegenDir] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, sc] = await Promise.all([
        api.getArtifact<StrategyJson>(task.id, "strategy"),
        api.getArtifact<ScriptsFinalJson>(task.id, "scripts_final"),
      ]);
      setStrategy(s);
      setScripts(sc);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, [task.id]);

  useEffect(() => {
    load();
  }, [load]);

  const variants = strategy?.variants ?? [];
  const scriptByVid: Record<string, ScriptEntry> = {};
  (scripts?.scripts ?? []).forEach((s) => {
    if (s.variant_id) scriptByVid[s.variant_id] = s;
  });

  const selectedIds = Object.keys(selected).filter((k) => selected[k]);
  const canProceed = selectedIds.length >= 1;

  function toggleAll(checked: boolean) {
    const next: Record<string, boolean> = {};
    for (const v of variants) {
      if (v.variant_id) next[v.variant_id] = checked;
    }
    setSelected(next);
  }

  async function submitNext() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, {
        step: "select_scripts",
        selected_variant_ids: selectedIds,
      });
      onChange();
      router.refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitRegenerate() {
    if (!regenTarget) return;
    setSubmitting(true);
    try {
      await api.regenerateScript(
        task.id,
        regenTarget,
        regenDir.trim() || undefined,
      );
      setRegenTarget(null);
      setRegenDir("");
      onChange();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <main className="mx-auto max-w-4xl p-8">
        <Card className="border-destructive/40">
          <CardContent className="py-6 text-sm text-destructive">
            대본/전략 파일 로드 실패: {loadError}
          </CardContent>
        </Card>
      </main>
    );
  }

  if (!strategy || !scripts) {
    return (
      <main className="mx-auto max-w-4xl p-8 text-sm text-muted-foreground">
        대본 불러오는 중…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{task.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Step 3/11 · 대본 선택 · {selectedIds.length}/{variants.length}개 선택
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => toggleAll(true)}
          >
            전체 선택
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => toggleAll(false)}
          >
            해제
          </Button>
        </div>
      </header>

      <div className="space-y-3">
        {variants.map((v) => (
          <VariantCard
            key={v.variant_id}
            variant={v}
            script={scriptByVid[v.variant_id]}
            checked={!!selected[v.variant_id]}
            onCheck={(c) =>
              setSelected((prev) => ({ ...prev, [v.variant_id]: c }))
            }
            onRegenerate={() => {
              setRegenTarget(v.variant_id);
              setRegenDir("");
            }}
            disabled={submitting || task.status === "running"}
          />
        ))}
      </div>

      <div className="flex justify-end gap-2">
        <Button
          size="lg"
          disabled={!canProceed || submitting}
          onClick={submitNext}
        >
          선택한 {selectedIds.length}개로 TTS 생성 →
        </Button>
      </div>

      <Dialog
        open={!!regenTarget}
        onOpenChange={(o) => !o && setRegenTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{regenTarget} 대본 재생성</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-sm font-medium">
              재생성 방향 (선택)
            </label>
            <Textarea
              rows={3}
              value={regenDir}
              onChange={(e) => setRegenDir(e.target.value)}
              placeholder="예: 더 감성적인 톤으로, 가격 정보 빼고"
            />
            <p className="text-xs text-muted-foreground">
              script_reviewer는 재호출하지 않습니다. 재생성된 대본은 자동 검수
              없이 그대로 반영됩니다. 변경 시 해당 variant의 TTS 파일은
              자동 삭제됩니다.
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRegenTarget(null)}>
              취소
            </Button>
            <Button onClick={submitRegenerate} disabled={submitting}>
              재생성
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function VariantCard({
  variant,
  script,
  checked,
  onCheck,
  onRegenerate,
  disabled,
}: {
  variant: StrategyVariant;
  script: ScriptEntry | undefined;
  checked: boolean;
  onCheck: (c: boolean) => void;
  onRegenerate: () => void;
  disabled: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 py-4">
        <div className="flex items-start gap-3">
          <Checkbox
            checked={checked}
            disabled={disabled}
            onCheckedChange={(c) => onCheck(c === true)}
            className="mt-1"
          />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold">{variant.variant_id}</span>
              {variant.hook_type && (
                <Badge variant="outline">{variant.hook_type}</Badge>
              )}
              {variant.target_emotion && (
                <Badge variant="secondary">{variant.target_emotion}</Badge>
              )}
            </div>
            {variant.direction && (
              <p className="mt-1 text-xs text-muted-foreground">
                방향: {variant.direction}
              </p>
            )}
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={onRegenerate}
          disabled={disabled}
        >
          🔄 재생성
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {script?.hook_text && (
          <div>
            <div className="text-xs font-medium text-muted-foreground">훅</div>
            <div className="mt-1">{script.hook_text}</div>
          </div>
        )}
        {script?.script_text && (
          <div>
            <div className="text-xs font-medium text-muted-foreground">
              대본 ({script.script_text.length}자)
            </div>
            <div className="mt-1 whitespace-pre-wrap">{script.script_text}</div>
          </div>
        )}
        {script?.title && (
          <div>
            <div className="text-xs font-medium text-muted-foreground">
              제목
            </div>
            <div className="mt-1">{script.title}</div>
          </div>
        )}
        {script?.hashtags && script.hashtags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {script.hashtags.map((h) => (
              <Badge key={h} variant="secondary" className="text-[10px]">
                #{h.replace(/^#/, "")}
              </Badge>
            ))}
          </div>
        )}
        {variant.clips && variant.clips.length > 0 && (
          <div className="rounded-md bg-muted/40 p-2 text-xs">
            <div className="font-medium">클립 배정 {variant.clips.length}개</div>
            <ul className="mt-1 space-y-1">
              {variant.clips.map((c) => (
                <li key={c.clip_num}>
                  #{c.clip_num} · {c.source_image} · {c.i2v_prompt?.slice(0, 60)}
                  {c.i2v_prompt && c.i2v_prompt.length > 60 ? "…" : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

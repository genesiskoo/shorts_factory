"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { API_BASE, api } from "@/lib/api";
import type {
  ScriptEntry,
  ScriptScene,
  StrategyScene,
  StrategyVariant,
} from "@/lib/types";

interface Props {
  taskId: number;
  taskImages: string[];
  variant: StrategyVariant;
  script: ScriptEntry | undefined;
  disabled: boolean;
  onEdited: () => void;
}

export function SceneStoryboard({
  taskId,
  taskImages,
  variant,
  script,
  disabled,
  onEdited,
}: Props) {
  const imageByKey = useMemo(() => {
    const m: Record<string, string> = {};
    taskImages.forEach((p, i) => {
      const basename = p.split(/[\\/]/).pop() ?? p;
      m[`img_${i + 1}`] = basename;
    });
    return m;
  }, [taskImages]);

  const sceneScripts = useMemo(() => {
    const m: Record<number, ScriptScene> = {};
    (script?.scenes ?? []).forEach((s) => {
      m[s.scene_num] = s;
    });
    return m;
  }, [script?.scenes]);

  const strategyScenes = variant.scenes ?? [];
  if (strategyScenes.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground">
          Storyboard · {strategyScenes.length} scenes
        </div>
        {script?.hook_text && (
          <div className="text-xs text-muted-foreground">
            훅 → S1, 마무리 → S{script.outro_attached_to ?? strategyScenes.length}
          </div>
        )}
      </div>
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
        {strategyScenes.map((scene) => (
          <SceneCard
            key={scene.scene_num}
            taskId={taskId}
            variantId={variant.variant_id}
            scene={scene}
            scriptScene={sceneScripts[scene.scene_num]}
            imageBasename={imageByKey[scene.source_image]}
            disabled={disabled}
            onEdited={onEdited}
          />
        ))}
      </div>
    </div>
  );
}

function SceneCard({
  taskId,
  variantId,
  scene,
  scriptScene,
  imageBasename,
  disabled,
  onEdited,
}: {
  taskId: number;
  variantId: string;
  scene: StrategyScene;
  scriptScene: ScriptScene | undefined;
  imageBasename: string | undefined;
  disabled: boolean;
  onEdited: () => void;
}) {
  const segment = scriptScene?.script_segment ?? "";
  const refined =
    scriptScene?.i2v_prompt_refined ??
    scene.i2v_prompt_refined ??
    scene.i2v_prompt_baseline ??
    "";

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(segment);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(segment);
  }, [segment, editing]);

  useEffect(() => {
    if (disabled && editing) {
      setEditing(false);
      setDraft(segment);
    }
  }, [disabled, editing, segment]);

  const imageUrl = imageBasename
    ? `${API_BASE}/api/tasks/${taskId}/image/${encodeURIComponent(imageBasename)}`
    : null;

  async function save() {
    const trimmed = draft.trim();
    if (trimmed.length < 1) {
      toast.error("Scene 대본은 비울 수 없습니다.");
      return;
    }
    if (trimmed === segment) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await api.editScript(taskId, variantId, trimmed, scene.scene_num);
      setEditing(false);
      onEdited();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setDraft(segment);
    setEditing(false);
  }

  return (
    <div className="flex w-72 shrink-0 flex-col gap-2 rounded-md border bg-card p-2">
      <div className="flex items-center justify-between gap-1 text-[11px] text-muted-foreground">
        <span className="font-semibold text-foreground">
          S{scene.scene_num}
        </span>
        <div className="flex items-center gap-1">
          {scene.timeline && (
            <Badge variant="outline" className="px-1 py-0 text-[10px]">
              {scene.timeline}
            </Badge>
          )}
          <span>{scene.expected_duration_sec ?? 7}s</span>
        </div>
      </div>

      <div className="relative aspect-[9/16] w-full overflow-hidden rounded bg-muted">
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt={`scene ${scene.scene_num}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] text-muted-foreground">
            {scene.source_image}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground">대본 조각</span>
          {!editing && !disabled && (
            <button
              type="button"
              aria-label={`scene ${scene.scene_num} 대본 편집`}
              className="text-[10px] text-muted-foreground hover:text-foreground"
              onClick={() => setEditing(true)}
            >
              ✏️ 편집
            </button>
          )}
        </div>
        {editing ? (
          <div className="space-y-1">
            <Textarea
              rows={4}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={saving}
              className="text-xs"
            />
            <div className="flex justify-end gap-1">
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                onClick={cancel}
                disabled={saving}
              >
                취소
              </Button>
              <Button
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={save}
                disabled={
                  saving ||
                  draft.trim().length < 1 ||
                  draft.trim() === segment.trim()
                }
              >
                {saving ? "저장 중…" : "저장"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="min-h-[3.5rem] whitespace-pre-wrap text-xs leading-snug">
            {segment || (
              <span className="text-muted-foreground/60">(대본 없음)</span>
            )}
          </p>
        )}
      </div>

      {scene.scene_intent && (
        <details className="text-[10px] text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">
            의도 / 영상 프롬프트
          </summary>
          <div className="mt-1 space-y-1 rounded bg-muted/40 p-1.5">
            <div>
              <span className="font-medium">intent:</span> {scene.scene_intent}
            </div>
            {refined && (
              <div className="break-all font-mono">
                <span className="font-medium">i2v:</span> {refined}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

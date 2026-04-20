"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { DropVariantButton } from "@/components/DropVariantButton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { API_BASE, api } from "@/lib/api";
import type {
  I2VModelInfo,
  I2VModelsListResp,
  StrategyJson,
  StrategyVariant,
  TaskDetail,
} from "@/lib/types";

interface ClipRowProps {
  taskId: number;
  variantId: string;
  clipNum: number;
  sourceImage: string;
  timeline?: string;
  prompt: string;
  thumbUrl: string | null;
  onEdited: () => void;
  disabled: boolean;
}

function ClipRow({
  taskId,
  variantId,
  clipNum,
  sourceImage,
  timeline,
  prompt,
  thumbUrl,
  onEdited,
  disabled,
}: ClipRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(prompt);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(prompt);
  }, [prompt, editing]);

  async function save() {
    const trimmed = draft.trim();
    if (trimmed.length < 5) {
      toast.error("프롬프트는 최소 5자 이상이어야 합니다.");
      return;
    }
    setSaving(true);
    try {
      await api.editPrompt(taskId, variantId, clipNum, trimmed);
      setEditing(false);
      onEdited();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setDraft(prompt);
    setEditing(false);
  }

  return (
    <div className="flex gap-3 rounded-md border p-2">
      {thumbUrl && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={thumbUrl}
          alt={sourceImage}
          className="h-20 w-20 flex-shrink-0 rounded object-cover"
        />
      )}
      <div className="min-w-0 flex-1 space-y-1 text-sm">
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="secondary">Clip {clipNum}</Badge>
            <Badge variant="outline">{sourceImage}</Badge>
            {timeline && <Badge>{timeline}</Badge>}
          </div>
          {!editing && !disabled && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs"
              onClick={() => setEditing(true)}
            >
              ✏️ 편집
            </Button>
          )}
        </div>
        {editing ? (
          <div className="space-y-2 pt-1">
            <p className="text-[11px] text-amber-600">
              가드 키워드 유지 권장: <code className="font-mono">no text on screen</code>,{" "}
              <code className="font-mono">preserve product appearance unchanged</code>{" "}
              — 저비용 모델의 텍스트 자동 생성·상품 변형 방지
            </p>
            <Textarea
              rows={4}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={saving}
              className="text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              저장 시 stale 상태의 기존 클립 mp4는 삭제되어 다음 영상 생성에서
              재생성됩니다.
            </p>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={cancel}
                disabled={saving}
              >
                취소
              </Button>
              <Button
                size="sm"
                onClick={save}
                disabled={saving || draft === prompt || draft.trim().length < 5}
              >
                {saving ? "저장 중…" : "저장"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground">{prompt}</p>
        )}
      </div>
    </div>
  );
}

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
  const [modelInfo, setModelInfo] = useState<I2VModelInfo | null>(null);
  const [modelList, setModelList] = useState<I2VModelsListResp | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(
    task.i2v_model ?? null,
  );

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

  useEffect(() => {
    api
      .getModelsConfig()
      .then((r) => setModelInfo(r.i2v))
      .catch(() => {});
    api
      .listI2VModels()
      .then((r) => {
        setModelList(r);
        if (!task.i2v_model) {
          setSelectedModel(r.default_chain[0] ?? r.config_default);
        }
      })
      .catch(() => {});
  }, [task.i2v_model]);

  const activeModel = useMemo(() => {
    if (!modelList) return modelInfo;
    return (
      modelList.models.find((m) => m.model === selectedModel) ?? modelInfo
    );
  }, [modelList, modelInfo, selectedModel]);

  const fallbackChain = useMemo(() => {
    if (!modelList) return [];
    const chain: string[] = [];
    if (selectedModel) chain.push(selectedModel);
    for (const m of modelList.default_chain) {
      if (!chain.includes(m)) chain.push(m);
    }
    return chain;
  }, [modelList, selectedModel]);

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
  const secPerClip = activeModel?.expected_sec_per_clip ?? 90;
  const estSec = totalClips * secPerClip;
  const estMin = Math.round(estSec / 60);

  async function startVideo() {
    setSubmitting(true);
    try {
      await api.nextStep(task.id, {
        step: "review_prompts",
        i2v_model: selectedModel ?? undefined,
      });
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function goBack() {
    setSubmitting(true);
    try {
      await api.backStep(task.id);
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
        <CardContent className="space-y-3 py-4 text-sm">
          {modelList && modelList.models.length > 0 && (
            <div className="space-y-2 border-b border-amber-500/30 pb-3">
              <div className="flex items-center justify-between gap-2">
                <label
                  htmlFor="i2v-model-select"
                  className="text-xs font-semibold"
                >
                  영상 모델 선택
                </label>
                <span className="text-[10px] text-muted-foreground">
                  실패 시 폴백 체인으로 자동 재시도
                </span>
              </div>
              <Select
                value={selectedModel ?? undefined}
                onValueChange={(v) => setSelectedModel(v)}
                disabled={submitting || task.status === "running"}
              >
                <SelectTrigger
                  id="i2v-model-select"
                  className="h-9 bg-background text-xs"
                >
                  <SelectValue placeholder="모델 선택…" />
                </SelectTrigger>
                <SelectContent>
                  {modelList.models.map((m) => (
                    <SelectItem key={m.model} value={m.model}>
                      <div className="flex flex-col items-start gap-0.5 py-1">
                        <span className="text-xs font-medium">
                          {m.label}
                          {m.daily_quota_estimate != null &&
                            ` · 일 ${m.daily_quota_estimate}클립`}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          {m.notes}
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {fallbackChain.length > 1 && (
                <div className="text-[10px] text-muted-foreground">
                  폴백 순서: {fallbackChain.join(" → ")}
                </div>
              )}
              {activeModel && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge className="bg-amber-600 text-white hover:bg-amber-700">
                    {activeModel.family}
                  </Badge>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                    {activeModel.model}
                  </code>
                </div>
              )}
            </div>
          )}
          <ul className="space-y-1">
            <li>
              ⚠️ 총 {totalClips}개 클립 생성 예정 · 클립당 약 {secPerClip}초 소요
            </li>
            <li>
              ⚠️ {activeModel?.label ?? "Veo"} 크레딧 차감
              {activeModel?.daily_quota_estimate != null &&
                ` · 일일 쿼터 약 ${activeModel.daily_quota_estimate}클립 제한`}
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
              <DropVariantButton
                taskId={task.id}
                variantId={v.variant_id}
                remainingCount={variants.length}
                onDropped={onChange}
                disabled={submitting || task.status === "running"}
              />
            </CardHeader>
            <CardContent className="space-y-2">
              {(v.clips ?? []).map((c) => {
                const basename = imageByKey[c.source_image];
                const thumb = basename
                  ? `${API_BASE}/api/tasks/${task.id}/image/${encodeURIComponent(basename)}`
                  : null;
                return (
                  <ClipRow
                    key={c.clip_num}
                    taskId={task.id}
                    variantId={v.variant_id}
                    clipNum={c.clip_num}
                    sourceImage={c.source_image}
                    timeline={c.timeline}
                    prompt={c.i2v_prompt ?? ""}
                    thumbUrl={thumb}
                    onEdited={load}
                    disabled={submitting || task.status === "running"}
                  />
                );
              })}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={goBack} disabled={submitting}>
          ← 이전 (TTS 검수)
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

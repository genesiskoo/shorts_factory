"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import {
  CAMPAIGN_VARIANTS,
  type CampaignVariant,
  type TaskDetail,
} from "@/lib/types";

const TEMPLATES = [
  { value: "default", label: "기본형", description: "세로형 9:16, TTS+클립+자막+BGM" },
];

export function SelectTemplate({
  task,
  onChange,
}: {
  task: TaskDetail;
  onChange: () => void;
}) {
  const [template, setTemplate] = useState("default");
  const [campaign, setCampaign] = useState<CampaignVariant>(
    (task.campaign_variant as CampaignVariant) ?? "none",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function build() {
    setSubmitting(true);
    setError(null);
    try {
      const assignments: Record<string, string> = {};
      for (const vid of task.selected_variant_ids) assignments[vid] = template;
      await api.buildCapcut(task.id, assignments, campaign);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{task.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Step 10/11 · CapCut 템플릿 선택
          </p>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">← 홈</Link>
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">템플릿</CardTitle>
        </CardHeader>
        <CardContent>
          <RadioGroup value={template} onValueChange={setTemplate}>
            {TEMPLATES.map((t) => (
              <div key={t.value} className="flex items-start gap-3">
                <RadioGroupItem value={t.value} id={`tpl-${t.value}`} className="mt-1" />
                <Label htmlFor={`tpl-${t.value}`} className="flex-1 cursor-pointer">
                  <div className="font-medium">{t.label}</div>
                  <div className="text-xs text-muted-foreground">
                    {t.description}
                  </div>
                </Label>
              </div>
            ))}
          </RadioGroup>
          <p className="mt-3 text-xs text-muted-foreground">
            Phase 2에서 스펙강조형 / 감성형 / 비교형 3종 추가 예정.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">캠페인</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Select
            value={campaign}
            onValueChange={(v) => setCampaign(v as CampaignVariant)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CAMPAIGN_VARIANTS.map((c) => (
                <SelectItem key={c.value} value={c.value}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            MVP에서는 DB 저장만. 실제 로고 오버레이는 Phase 2.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">대상 variant</CardTitle>
        </CardHeader>
        <CardContent className="text-sm">
          <ul className="space-y-1">
            {task.selected_variant_ids.map((vid) => (
              <li key={vid} className="flex items-center justify-between">
                <span>{vid}</span>
                <code className="rounded bg-muted px-2 py-0.5 text-xs">
                  {template}
                </code>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="py-3 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end">
        <Button
          size="lg"
          onClick={build}
          disabled={submitting || task.status === "running"}
        >
          🎬 CapCut 프로젝트 생성 →
        </Button>
      </div>
    </main>
  );
}

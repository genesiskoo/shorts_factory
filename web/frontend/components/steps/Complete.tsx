"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { API_BASE } from "@/lib/api";
import type { TaskDetail } from "@/lib/types";

export function Complete({ task }: { task: TaskDetail }) {
  const elapsed =
    task.completed_at && task.created_at
      ? Math.round(
          (new Date(task.completed_at).getTime() -
            new Date(task.created_at).getTime()) /
            1000,
        )
      : null;
  const elapsedMin = elapsed != null ? Math.floor(elapsed / 60) : null;
  const elapsedSec = elapsed != null ? elapsed % 60 : null;

  async function copyFolder() {
    if (!task.output_dir) return;
    try {
      await navigator.clipboard.writeText(task.output_dir);
      alert("경로를 클립보드에 복사했습니다.");
    } catch {
      alert(task.output_dir);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header className="space-y-1">
        <Badge className="bg-green-600 hover:bg-green-700">완료</Badge>
        <h1 className="text-2xl font-bold">{task.product_name}</h1>
        <p className="text-sm text-muted-foreground">
          Step 11/11 · 다운로드
          {elapsed != null && ` · 총 ${elapsedMin}분 ${elapsedSec}초 소요`}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">생성된 CapCut 프로젝트</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {task.selected_variant_ids.length === 0 && (
            <p className="text-sm text-muted-foreground">
              variant 정보를 찾을 수 없습니다.
            </p>
          )}
          {task.selected_variant_ids.map((vid) => (
            <div
              key={vid}
              className="flex items-center justify-between gap-3 rounded-md border p-3"
            >
              <div>
                <div className="font-medium">{vid}</div>
                <div className="text-xs text-muted-foreground">
                  {task.product_name}_{vid}.zip
                </div>
              </div>
              <Button asChild variant="outline" size="sm">
                <a
                  href={`${API_BASE}/api/tasks/${task.id}/download/${vid}`}
                  download
                >
                  ⬇️ 다운로드
                </a>
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>

      {task.output_dir && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">출력 폴더</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <code className="block break-all rounded bg-muted px-3 py-2 text-xs">
              {task.output_dir}
            </code>
            <Button variant="ghost" size="sm" onClick={copyFolder}>
              📋 경로 복사
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">다음 단계</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>1. 다운로드한 zip을 CapCut 드래프트 폴더에 풀어넣기</p>
          <p>2. CapCut 데스크톱에서 프로젝트 열어 최종 검토 / 렌더링</p>
          <p>3. YouTube Shorts / Instagram Reels / TikTok 업로드</p>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button asChild variant="outline">
          <Link href="/">← 홈</Link>
        </Button>
        <Button asChild>
          <Link href="/new">+ 새 작업 시작</Link>
        </Button>
      </div>
    </main>
  );
}

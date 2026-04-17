"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { HealthResp, TaskSummary } from "@/lib/types";

export default function HomePage() {
  const [health, setHealth] = useState<HealthResp | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const [h, t] = await Promise.all([api.health(), api.listTasks()]);
        if (cancelled) return;
        setHealth(h);
        setTasks(t.tasks);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    }

    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const inProgress = (tasks ?? []).filter(
    (t) =>
      t.status === "pending" ||
      t.status === "running" ||
      t.status === "awaiting_user",
  );
  const completed = (tasks ?? []).filter((t) => t.status === "completed");
  const failed = (tasks ?? []).filter((t) => t.status === "failed");

  return (
    <main className="mx-auto max-w-4xl p-8 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">shorts_factory</h1>
          <p className="text-sm text-muted-foreground">
            Backend:{" "}
            {health ? (
              <Badge variant="outline" className="ml-1">
                {health.status}
              </Badge>
            ) : error ? (
              <Badge variant="destructive" className="ml-1">
                offline
              </Badge>
            ) : (
              <Badge variant="secondary" className="ml-1">
                checking…
              </Badge>
            )}
          </p>
        </div>
        <Button asChild>
          <Link href="/new">+ 새 작업</Link>
        </Button>
      </header>

      {error && (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">백엔드 연결 실패</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {error}
            <div className="mt-2">
              <code className="rounded bg-muted px-2 py-1 text-xs">
                cd web/backend &amp;&amp; uvicorn main:app --reload --port 8000
              </code>
            </div>
          </CardContent>
        </Card>
      )}

      <Section
        title="진행 중 / 대기 중"
        tasks={inProgress}
        emptyMsg="진행 중인 작업이 없습니다."
      />
      <Section
        title="완료"
        tasks={completed}
        emptyMsg="완료된 작업이 없습니다."
      />
      {failed.length > 0 && (
        <Section title="실패" tasks={failed} emptyMsg="" />
      )}
    </main>
  );
}

function Section({
  title,
  tasks,
  emptyMsg,
}: {
  title: string;
  tasks: TaskSummary[];
  emptyMsg: string;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {tasks.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyMsg}</p>
      ) : (
        <div className="grid gap-3">
          {tasks.map((t) => (
            <Card key={t.id}>
              <CardContent className="flex items-center justify-between py-4">
                <div>
                  <div className="font-medium">{t.product_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(t.created_at).toLocaleString()} · {t.status}
                    {t.current_step ? ` · ${t.current_step}` : ""}
                  </div>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link href={`/tasks/${t.id}`}>
                    {t.status === "completed" ? "열기" : "이어하기"} →
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}

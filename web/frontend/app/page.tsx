"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { HealthResp, TaskSummary } from "@/lib/types";

export default function HomePage() {
  const [health, setHealth] = useState<HealthResp | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TaskSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function refresh() {
    try {
      const [h, t] = await Promise.all([api.health(), api.listTasks()]);
      setHealth(h);
      setTasks(t.tasks);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      await refresh();
    }

    tick();
    const timer = window.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await api.deleteTask(deleteTarget.id);
      if (res.warning) {
        toast.warning(res.warning, { duration: 8000 });
      } else {
        toast.success(`"${res.product_name}" 삭제됨`);
      }
      setDeleteTarget(null);
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  }

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
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <span>Backend:</span>
            {health ? (
              <Badge variant="outline">{health.status}</Badge>
            ) : error ? (
              <Badge variant="destructive">offline</Badge>
            ) : (
              <Badge variant="secondary">checking…</Badge>
            )}
          </div>
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
        onDelete={setDeleteTarget}
      />
      <Section
        title="완료"
        tasks={completed}
        emptyMsg="완료된 작업이 없습니다."
        onDelete={setDeleteTarget}
      />
      {failed.length > 0 && (
        <Section
          title="실패"
          tasks={failed}
          emptyMsg=""
          onDelete={setDeleteTarget}
        />
      )}

      <Dialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && !deleting && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>작업 삭제</DialogTitle>
          </DialogHeader>
          {deleteTarget && (
            <div className="space-y-3 text-sm">
              <p>
                <span className="font-semibold">
                  {deleteTarget.product_name}
                </span>{" "}
                작업을 삭제하시겠습니까?
              </p>
              <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                <li>DB 레코드, 업로드 이미지, output 폴더 전체가 삭제됩니다.</li>
                <li>되돌릴 수 없습니다.</li>
                {deleteTarget.status === "running" && (
                  <li className="text-amber-700">
                    진행 중인 작업입니다. Veo/ElevenLabs 호출은 취소되지
                    않으므로 완료 후 고아 파일이 남을 수 있습니다.
                  </li>
                )}
              </ul>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={confirmDelete}
              disabled={deleting}
            >
              {deleting ? "삭제 중…" : "삭제"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function Section({
  title,
  tasks,
  emptyMsg,
  onDelete,
}: {
  title: string;
  tasks: TaskSummary[];
  emptyMsg: string;
  onDelete: (task: TaskSummary) => void;
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
                <div className="flex items-center gap-2">
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/tasks/${t.id}`}>
                      {t.status === "completed" ? "열기" : "이어하기"} →
                    </Link>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => onDelete(t)}
                    aria-label={`${t.product_name} 삭제`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}

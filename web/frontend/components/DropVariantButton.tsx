"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";

interface Props {
  taskId: number;
  variantId: string;
  remainingCount: number;
  onDropped: () => void;
  disabled?: boolean;
  /** sm: 카드 헤더 / icon: 탭 트리거 바로 옆 */
  size?: "sm" | "icon";
}

/**
 * 선택된 variant를 이후 파이프라인에서 영구 제외.
 * 최소 1개 유지 가드(remainingCount <= 1)를 내장.
 * artifact 파일(audio/clip)은 백엔드에서 보존(delete-task 때 일괄 정리).
 */
export function DropVariantButton({
  taskId,
  variantId,
  remainingCount,
  onDropped,
  disabled,
  size = "sm",
}: Props) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const canDrop = remainingCount > 1 && !disabled;

  async function confirm() {
    setSubmitting(true);
    try {
      const res = await api.dropVariant(taskId, variantId);
      toast.success(
        `${res.dropped} 제외됨 · 남은 ${res.remaining.length}개`,
      );
      setOpen(false);
      onDropped();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      {size === "icon" ? (
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          onClick={() => setOpen(true)}
          disabled={!canDrop}
          aria-label={`${variantId} 제외`}
          title={
            canDrop
              ? `${variantId} 제외`
              : "최소 1개의 variant는 유지해야 합니다"
          }
        >
          <X className="h-4 w-4" />
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          onClick={() => setOpen(true)}
          disabled={!canDrop}
          title={
            canDrop ? undefined : "최소 1개의 variant는 유지해야 합니다"
          }
        >
          <X className="h-4 w-4" />
          제외
        </Button>
      )}

      <Dialog
        open={open}
        onOpenChange={(o) => !submitting && setOpen(o)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{variantId} 제외</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p>
              <span className="font-semibold">{variantId}</span>를 이후 파이프라인에서
              제외하시겠습니까?
            </p>
            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              <li>다음 단계부터 이 variant는 포함되지 않습니다.</li>
              <li>이미 생성된 audio/클립 파일은 디스크에 보존됩니다 (delete-task 때 일괄 정리).</li>
              <li>되돌릴 수 없습니다.</li>
            </ul>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={confirm}
              disabled={submitting}
            >
              {submitting ? "제외 중…" : "제외"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED = ["image/jpeg", "image/png", "image/webp"];

interface ImageDropzoneProps {
  files: File[];
  onChange: (files: File[]) => void;
  min?: number;
  max?: number;
}

export function ImageDropzone({
  files,
  onChange,
  min = 3,
  max = 5,
}: ImageDropzoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [previews, setPreviews] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => {
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [files]);

  const addFiles = useCallback(
    (incoming: File[]) => {
      const merged = [...files];
      for (const f of incoming) {
        if (merged.length >= max) break;
        if (!ALLOWED.includes(f.type)) continue;
        if (f.size > MAX_BYTES) continue;
        if (merged.some((m) => m.name === f.name && m.size === f.size)) continue;
        merged.push(f);
      }
      onChange(merged);
    },
    [files, onChange, max],
  );

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    addFiles(Array.from(e.dataTransfer.files));
  }

  function handlePick(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  }

  function removeAt(idx: number) {
    onChange(files.filter((_, i) => i !== idx));
  }

  function moveItem(from: number, to: number) {
    if (to < 0 || to >= files.length) return;
    const next = [...files];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
  }

  const countOk = files.length >= min && files.length <= max;
  const countMsg =
    files.length < min
      ? `최소 ${min}장 필요 (현재 ${files.length}장)`
      : files.length > max
        ? `최대 ${max}장 (현재 ${files.length}장)`
        : `${files.length}/${max}장`;

  return (
    <div className="space-y-3">
      <div
        className={`rounded-lg border-2 border-dashed p-6 text-center transition ${
          dragOver ? "border-primary bg-primary/5" : "border-muted-foreground/30"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <p className="text-sm text-muted-foreground">
          이미지를 여기에 드래그하거나
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => inputRef.current?.click()}
          disabled={files.length >= max}
        >
          파일 선택
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED.join(",")}
          multiple
          hidden
          onChange={handlePick}
        />
        <p className={`mt-2 text-xs ${countOk ? "text-muted-foreground" : "text-destructive"}`}>
          {countMsg} · jpg/png/webp, 각 10MB 이하
        </p>
      </div>

      {files.length > 0 && (
        <ul className="grid grid-cols-3 gap-3 md:grid-cols-5">
          {files.map((f, idx) => (
            <li
              key={`${f.name}-${f.size}-${idx}`}
              className="relative overflow-hidden rounded-md border bg-muted/30"
            >
              {previews[idx] && (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={previews[idx]}
                  alt={f.name}
                  className="aspect-square w-full object-cover"
                />
              )}
              <div className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                img_{idx + 1}
              </div>
              <div className="flex items-center justify-between gap-1 p-1 text-[10px]">
                <button
                  type="button"
                  onClick={() => moveItem(idx, idx - 1)}
                  className="rounded px-1 hover:bg-muted disabled:opacity-30"
                  disabled={idx === 0}
                >
                  ←
                </button>
                <button
                  type="button"
                  onClick={() => removeAt(idx)}
                  className="rounded bg-destructive/10 px-1 text-destructive hover:bg-destructive/20"
                >
                  삭제
                </button>
                <button
                  type="button"
                  onClick={() => moveItem(idx, idx + 1)}
                  className="rounded px-1 hover:bg-muted disabled:opacity-30"
                  disabled={idx === files.length - 1}
                >
                  →
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

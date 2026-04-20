"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type {
  TaskDetail,
  TtsOptions,
  TtsProvider,
  TtsVoice,
} from "@/lib/types";

const DEFAULT_MODEL = "ssfm-v30";
const PREVIEW_DEFAULT_SAMPLE = "안녕하세요. 이 목소리로 대본을 읽어드립니다.";
const PREVIEW_SAMPLE_MAX = 150;

const EMOTION_PRESETS = [
  "normal",
  "happy",
  "sad",
  "angry",
  "whisper",
  "toneup",
  "tonedown",
] as const;

function pickDefaultTypecastVoice(voices: TtsVoice[]): TtsVoice | undefined {
  if (voices.length === 0) return undefined;
  const isNarration = (v: TtsVoice) =>
    v.use_cases.some((u) =>
      /narration|ads|promotion|announcer|e-learning/i.test(u),
    );
  // 1) female + narration/ads
  const femaleNarration = voices.find(
    (v) => v.gender === "female" && isNarration(v),
  );
  if (femaleNarration) return femaleNarration;
  // 2) any female
  const anyFemale = voices.find((v) => v.gender === "female");
  if (anyFemale) return anyFemale;
  // 3) first
  return voices[0];
}

export function SelectTts({
  task,
  onChange,
}: {
  task: TaskDetail;
  onChange: () => void;
}) {
  const [provider, setProvider] = useState<TtsProvider>(
    task.tts_provider ?? "elevenlabs",
  );

  // Typecast 상태
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [voicesError, setVoicesError] = useState<string | null>(null);
  const [voiceId, setVoiceId] = useState<string>("");
  const [genderFilter, setGenderFilter] = useState<string>("all");
  const [useCaseFilter, setUseCaseFilter] = useState<string>("all");

  const [emotionType, setEmotionType] = useState<"smart" | "preset">("smart");
  const [emotionPreset, setEmotionPreset] = useState<string>("normal");
  const [emotionIntensity, setEmotionIntensity] = useState<number>(1.0);
  const [tempo, setTempo] = useState<number>(1.0);
  const [pitch, setPitch] = useState<number>(0);
  const [volume, setVolume] = useState<number>(100);
  const [audioFormat, setAudioFormat] = useState<"mp3" | "wav">("mp3");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Preview
  const [sampleText, setSampleText] = useState(PREVIEW_DEFAULT_SAMPLE);
  const [previewing, setPreviewing] = useState(false);
  const previewUrlRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // Submit/back
  const [submitting, setSubmitting] = useState(false);

  const loadVoices = useCallback(async () => {
    if (provider !== "typecast") return;
    setVoicesLoading(true);
    setVoicesError(null);
    try {
      const res = await api.listTtsVoices("typecast", DEFAULT_MODEL);
      setVoices(res.voices);
      // 초기 voice 자동 선정 (저장된 voice_id가 있으면 유지)
      const saved = task.tts_options?.voice_id;
      const hasSaved = saved && res.voices.some((v) => v.voice_id === saved);
      if (hasSaved) {
        setVoiceId(saved as string);
      } else {
        const d = pickDefaultTypecastVoice(res.voices);
        if (d) setVoiceId(d.voice_id);
      }
    } catch (e) {
      setVoicesError(e instanceof Error ? e.message : String(e));
    } finally {
      setVoicesLoading(false);
    }
  }, [provider, task.tts_options?.voice_id]);

  useEffect(() => {
    loadVoices();
  }, [loadVoices]);

  // 저장된 옵션이 있으면 초기 반영
  useEffect(() => {
    const o = task.tts_options;
    if (!o) return;
    if (o.emotion_type) setEmotionType(o.emotion_type);
    if (o.emotion_preset) setEmotionPreset(o.emotion_preset);
    if (typeof o.emotion_intensity === "number")
      setEmotionIntensity(o.emotion_intensity);
    if (typeof o.audio_tempo === "number") setTempo(o.audio_tempo);
    if (typeof o.audio_pitch === "number") setPitch(o.audio_pitch);
    if (typeof o.volume === "number") setVolume(o.volume);
    if (o.audio_format === "mp3" || o.audio_format === "wav")
      setAudioFormat(o.audio_format);
  }, [task.tts_options]);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const useCases = useMemo(() => {
    const s = new Set<string>();
    voices.forEach((v) => v.use_cases.forEach((u) => s.add(u)));
    return Array.from(s).sort();
  }, [voices]);

  const filteredVoices = useMemo(() => {
    return voices.filter((v) => {
      if (genderFilter !== "all" && v.gender !== genderFilter) return false;
      if (
        useCaseFilter !== "all" &&
        !v.use_cases.includes(useCaseFilter)
      )
        return false;
      return true;
    });
  }, [voices, genderFilter, useCaseFilter]);

  const activeVoice = voices.find((v) => v.voice_id === voiceId);

  function buildOptions(): TtsOptions {
    if (provider !== "typecast") return {};
    const opts: TtsOptions = {
      voice_id: voiceId,
      model: DEFAULT_MODEL,
      emotion_type: emotionType,
      audio_tempo: tempo,
      audio_pitch: pitch,
      volume,
      audio_format: audioFormat,
    };
    if (emotionType === "preset") {
      opts.emotion_preset = emotionPreset as TtsOptions["emotion_preset"];
      opts.emotion_intensity = emotionIntensity;
    }
    return opts;
  }

  async function doPreview() {
    if (provider !== "typecast") {
      toast.error("미리듣기는 현재 Typecast만 지원합니다.");
      return;
    }
    if (!voiceId) {
      toast.error("voice를 먼저 선택하세요.");
      return;
    }
    const text = sampleText.trim() || PREVIEW_DEFAULT_SAMPLE;
    if (text.length > PREVIEW_SAMPLE_MAX) {
      toast.error(`샘플 문장은 ${PREVIEW_SAMPLE_MAX}자 이내로.`);
      return;
    }
    setPreviewing(true);
    try {
      const blob = await api.previewTts(task.id, {
        provider: "typecast",
        options: buildOptions(),
        sample_text: text,
      });
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      if (audioRef.current) {
        audioRef.current.src = url;
        await audioRef.current.play().catch(() => {});
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewing(false);
    }
  }

  async function submitNext() {
    if (provider === "typecast" && !voiceId) {
      toast.error("voice를 선택하세요.");
      return;
    }
    setSubmitting(true);
    try {
      await api.nextStep(task.id, {
        step: "select_tts",
        tts_provider: provider,
        tts_options: buildOptions(),
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

  const disabled = submitting || task.status === "running";

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{task.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Step 3.5/11 · 보이스 선택 ·{" "}
            {task.selected_variant_ids.length}개 variant
          </p>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">← 홈</Link>
        </Button>
      </header>

      <Card>
        <CardHeader className="py-3">
          <Label className="font-semibold">TTS 제공자</Label>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={provider}
            onValueChange={(v) => setProvider(v as TtsProvider)}
            className="grid grid-cols-2 gap-3"
          >
            <label
              htmlFor="p-eleven"
              className={`flex cursor-pointer flex-col gap-1 rounded-md border p-3 text-sm ${provider === "elevenlabs" ? "border-primary ring-1 ring-primary" : ""}`}
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem id="p-eleven" value="elevenlabs" />
                <span className="font-medium">ElevenLabs</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Matilda 고정 · word-level SRT 자동 생성
              </p>
            </label>
            <label
              htmlFor="p-type"
              className={`flex cursor-pointer flex-col gap-1 rounded-md border p-3 text-sm ${provider === "typecast" ? "border-primary ring-1 ring-primary" : ""}`}
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem id="p-type" value="typecast" />
                <span className="font-medium">Typecast</span>
              </div>
              <p className="text-xs text-muted-foreground">
                한국어 200+ voice · Smart 감정 · SRT는 추정치
              </p>
            </label>
          </RadioGroup>
        </CardContent>
      </Card>

      {provider === "typecast" && (
        <Card>
          <CardHeader className="py-3">
            <Label className="font-semibold">Typecast 설정</Label>
          </CardHeader>
          <CardContent className="space-y-4">
            {voicesLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                voices 불러오는 중…
              </div>
            )}
            {voicesError && (
              <div className="text-sm text-destructive">{voicesError}</div>
            )}
            {!voicesLoading && !voicesError && voices.length > 0 && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <Label className="text-xs">성별</Label>
                    <Select
                      value={genderFilter}
                      onValueChange={setGenderFilter}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">전체</SelectItem>
                        <SelectItem value="female">여성</SelectItem>
                        <SelectItem value="male">남성</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="col-span-2">
                    <Label className="text-xs">용도</Label>
                    <Select
                      value={useCaseFilter}
                      onValueChange={setUseCaseFilter}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">전체</SelectItem>
                        {useCases.map((u) => (
                          <SelectItem key={u} value={u}>
                            {u}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div>
                  <Label className="text-xs">
                    Voice ({filteredVoices.length}/{voices.length})
                  </Label>
                  <Select value={voiceId} onValueChange={setVoiceId}>
                    <SelectTrigger>
                      <SelectValue placeholder="voice 선택" />
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      {filteredVoices.map((v) => (
                        <SelectItem key={v.voice_id} value={v.voice_id}>
                          <span className="flex items-center gap-2">
                            <span>{v.voice_name}</span>
                            {v.gender && (
                              <Badge variant="outline" className="text-[10px]">
                                {v.gender}
                              </Badge>
                            )}
                            {v.age && (
                              <Badge variant="secondary" className="text-[10px]">
                                {v.age}
                              </Badge>
                            )}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {activeVoice && activeVoice.use_cases.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {activeVoice.use_cases.slice(0, 4).join(" · ")}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="text-xs">감정 모드</Label>
                  <RadioGroup
                    value={emotionType}
                    onValueChange={(v) =>
                      setEmotionType(v as "smart" | "preset")
                    }
                    className="mt-1 grid grid-cols-2 gap-2"
                  >
                    <label
                      htmlFor="e-smart"
                      className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-xs ${emotionType === "smart" ? "border-primary" : ""}`}
                    >
                      <RadioGroupItem id="e-smart" value="smart" />
                      <div>
                        <div className="font-medium">Smart</div>
                        <div className="text-muted-foreground">
                          variant의 target_emotion/direction에서 자동 감지
                        </div>
                      </div>
                    </label>
                    <label
                      htmlFor="e-preset"
                      className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-xs ${emotionType === "preset" ? "border-primary" : ""}`}
                    >
                      <RadioGroupItem id="e-preset" value="preset" />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">Preset</div>
                        {emotionType === "preset" && (
                          <div className="mt-1 flex items-center gap-1">
                            <Select
                              value={emotionPreset}
                              onValueChange={setEmotionPreset}
                            >
                              <SelectTrigger className="h-7 text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {EMOTION_PRESETS.map((p) => (
                                  <SelectItem key={p} value={p}>
                                    {p}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        )}
                      </div>
                    </label>
                  </RadioGroup>
                  {emotionType === "preset" && (
                    <div className="mt-2">
                      <Label className="text-[11px]">
                        강도 {emotionIntensity.toFixed(1)}
                      </Label>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={0.1}
                        value={emotionIntensity}
                        onChange={(e) =>
                          setEmotionIntensity(Number(e.target.value))
                        }
                        className="w-full"
                      />
                    </div>
                  )}
                </div>

                <div>
                  <Label className="text-xs">
                    속도 (tempo) × {tempo.toFixed(2)}
                  </Label>
                  <input
                    type="range"
                    min={0.5}
                    max={2.0}
                    step={0.05}
                    value={tempo}
                    onChange={(e) => setTempo(Number(e.target.value))}
                    className="w-full"
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground">
                    <span>0.5 느림</span>
                    <span>1.0 기본</span>
                    <span>2.0 빠름</span>
                  </div>
                </div>

                <div>
                  <Label className="text-xs">Audio format</Label>
                  <RadioGroup
                    value={audioFormat}
                    onValueChange={(v) => setAudioFormat(v as "mp3" | "wav")}
                    className="mt-1 flex gap-4 text-sm"
                  >
                    <label className="flex items-center gap-1">
                      <RadioGroupItem id="f-mp3" value="mp3" /> mp3
                    </label>
                    <label className="flex items-center gap-1">
                      <RadioGroupItem id="f-wav" value="wav" /> wav
                    </label>
                  </RadioGroup>
                </div>

                <div>
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen((o) => !o)}
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >
                    {advancedOpen ? "▾ 고급 옵션 접기" : "▸ 고급 옵션 (pitch/volume)"}
                  </button>
                  {advancedOpen && (
                    <div className="mt-2 space-y-3 rounded-md border p-3">
                      <div>
                        <Label className="text-xs">Pitch {pitch}</Label>
                        <input
                          type="range"
                          min={-12}
                          max={12}
                          step={1}
                          value={pitch}
                          onChange={(e) => setPitch(Number(e.target.value))}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <Label className="text-xs">Volume {volume}</Label>
                        <input
                          type="range"
                          min={0}
                          max={200}
                          step={1}
                          value={volume}
                          onChange={(e) => setVolume(Number(e.target.value))}
                          className="w-full"
                        />
                      </div>
                    </div>
                  )}
                </div>

                <div className="space-y-2 rounded-md border p-3">
                  <Label className="text-xs font-semibold">
                    미리듣기 ({sampleText.length}/{PREVIEW_SAMPLE_MAX})
                  </Label>
                  <Input
                    value={sampleText}
                    onChange={(e) => setSampleText(e.target.value)}
                    maxLength={PREVIEW_SAMPLE_MAX}
                    placeholder={PREVIEW_DEFAULT_SAMPLE}
                    className="text-sm"
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      onClick={doPreview}
                      disabled={previewing || !voiceId}
                    >
                      {previewing ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin" />
                          생성 중…
                        </>
                      ) : (
                        "▶ 미리듣기"
                      )}
                    </Button>
                    {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                    <audio ref={audioRef} controls className="h-8 flex-1" />
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    미리듣기 최대 10회/task.
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {provider === "elevenlabs" && (
        <Card>
          <CardContent className="py-4 text-sm text-muted-foreground">
            ElevenLabs · Matilda 고정. 추가 옵션은 현재 미지원(향후 확장).
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={goBack} disabled={disabled}>
          ← 이전 (대본 선택)
        </Button>
        <Button
          size="lg"
          onClick={submitNext}
          disabled={
            disabled || (provider === "typecast" && !voiceId)
          }
        >
          TTS 생성 시작 →
        </Button>
      </div>
    </main>
  );
}

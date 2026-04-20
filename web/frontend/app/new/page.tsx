"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { ImageDropzone } from "@/components/ImageDropzone";
import { api } from "@/lib/api";
import { CAMPAIGN_VARIANTS, type CampaignVariant } from "@/lib/types";

export default function NewTaskPage() {
  const router = useRouter();
  const [productName, setProductName] = useState("");
  const [priceInfo, setPriceInfo] = useState("");
  const [detailText, setDetailText] = useState("");
  const [sellerMemo, setSellerMemo] = useState("");
  const [campaign, setCampaign] = useState<CampaignVariant>("none");
  const [landingUrl, setLandingUrl] = useState("");
  const [couponInfo, setCouponInfo] = useState("");
  const [originalPrice, setOriginalPrice] = useState<string>("");
  const [salePrice, setSalePrice] = useState<string>("");
  const [targetCharCount, setTargetCharCount] = useState<number | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 이미지 수 기반 target 상한/기본 (backend 상수와 일치)
  const { maxChars, defaultChars, videoSec } = useMemo(() => {
    const n = images.length;
    return {
      maxChars: Math.min(500, n * 49),
      defaultChars: Math.min(500, n * 45),
      videoSec: Math.round(n * 7),
    };
  }, [images.length]);

  // 이미지 수 변경 시 target을 기본값으로 초기화 또는 상한 클램프
  useEffect(() => {
    if (images.length === 0) return;
    setTargetCharCount((prev) => {
      if (prev === null) return defaultChars;
      if (prev > maxChars) return maxChars;
      return prev;
    });
  }, [maxChars, defaultChars, images.length]);

  const effectiveTarget = targetCharCount ?? defaultChars;
  const overCap = images.length > 0 && effectiveTarget > maxChars;

  // 할인률 자동 계산. 둘 다 채워지고 sale<original일 때만 표시.
  const orig = Number(originalPrice) || 0;
  const sale = Number(salePrice) || 0;
  const discountRate =
    orig > 0 && sale > 0 && sale < orig
      ? Math.round(((orig - sale) / orig) * 100)
      : null;
  const promoActive = campaign !== "none" && discountRate !== null;

  async function submit() {
    setError(null);
    if (!productName.trim()) {
      setError("상품명을 입력해주세요.");
      return;
    }
    if (images.length < 3 || images.length > 5) {
      setError("이미지는 3~5장이 필요합니다.");
      return;
    }
    if (effectiveTarget < 100 || effectiveTarget > 500) {
      setError("목표 글자수는 100~500 범위여야 합니다.");
      return;
    }
    if (effectiveTarget > maxChars) {
      setError(
        `이미지 ${images.length}장 기준 최대 ${maxChars}자까지 가능합니다. 이미지를 더 올리거나 글자수를 낮춰주세요.`,
      );
      return;
    }
    if ((originalPrice || salePrice) && !(orig > 0 && sale > 0 && sale <= orig)) {
      setError(
        "원가/할인가는 둘 다 양수여야 하고 할인가 ≤ 원가 조건을 만족해야 합니다.",
      );
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("product_name", productName.trim());
      if (priceInfo) fd.append("price_info", priceInfo);
      if (detailText) fd.append("detail_text", detailText);
      if (sellerMemo) fd.append("seller_memo", sellerMemo);
      fd.append("campaign_variant", campaign);
      if (landingUrl) fd.append("landing_url", landingUrl);
      if (couponInfo) fd.append("coupon_info", couponInfo);
      if (orig > 0) fd.append("original_price", String(orig));
      if (sale > 0) fd.append("sale_price", String(sale));
      fd.append("target_char_count", String(effectiveTarget));
      for (const img of images) fd.append("images", img);
      const resp = await api.createTask(fd);
      router.push(`/tasks/${resp.task_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">새 작업</h1>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">← 홈</Link>
        </Button>
      </header>

      <Card>
        <CardContent className="space-y-4 py-6">
          <div className="space-y-2">
            <Label htmlFor="product_name">
              상품명 <span className="text-destructive">*</span>
            </Label>
            <Input
              id="product_name"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="예: AULA F99 무선 키보드"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="price">가격 정보 (메모)</Label>
            <Input
              id="price"
              value={priceInfo}
              onChange={(e) => setPriceInfo(e.target.value)}
              placeholder="예: 169,700원 (쿠폰 15%)"
            />
          </div>

          <div className="space-y-2">
            <Label>
              프로모션 가격{" "}
              <span className="text-xs text-muted-foreground">
                (campaign 선택 + 둘 다 입력 시 v6_promotion 영상 추가)
              </span>
            </Label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Input
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={originalPrice}
                  onChange={(e) => setOriginalPrice(e.target.value)}
                  placeholder="원가 (예: 122000)"
                />
              </div>
              <div>
                <Input
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={salePrice}
                  onChange={(e) => setSalePrice(e.target.value)}
                  placeholder="할인가 (예: 36600)"
                />
              </div>
            </div>
            {discountRate !== null && (
              <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                <span className="text-muted-foreground line-through">
                  {orig.toLocaleString()}원
                </span>
                <span className="rounded-full bg-rose-500 px-2 py-0.5 text-xs font-bold text-white">
                  {discountRate}%
                </span>
                <span className="font-bold text-rose-600">
                  {sale.toLocaleString()}원
                </span>
                {!promoActive && (
                  <span className="ml-auto text-xs text-amber-600">
                    캠페인 선택 시 v6_promotion 자동 추가
                  </span>
                )}
                {promoActive && (
                  <span className="ml-auto text-xs text-emerald-600">
                    ✓ v6_promotion 활성
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="detail">상세 설명</Label>
            <Textarea
              id="detail"
              value={detailText}
              onChange={(e) => setDetailText(e.target.value)}
              rows={3}
              placeholder="제품 특징, 스펙, 타겟 고객 등"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="memo">판매자 메모</Label>
            <Textarea
              id="memo"
              value={sellerMemo}
              onChange={(e) => setSellerMemo(e.target.value)}
              rows={2}
              placeholder="내부 참고사항"
            />
          </div>

          <div className="space-y-2">
            <Label>
              이미지 <span className="text-destructive">*</span>
            </Label>
            <ImageDropzone files={images} onChange={setImages} />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>캠페인</Label>
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
            </div>
            <div className="space-y-2">
              <Label htmlFor="landing">랜딩 URL</Label>
              <Input
                id="landing"
                value={landingUrl}
                onChange={(e) => setLandingUrl(e.target.value)}
                placeholder="https://..."
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="coupon">쿠폰 정보</Label>
            <Input
              id="coupon"
              value={couponInfo}
              onChange={(e) => setCouponInfo(e.target.value)}
              placeholder="예: 15% 할인 쿠폰"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="target_chars">
              대본 목표 글자수{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {images.length === 0
                  ? "(이미지 업로드 후 활성화)"
                  : `(${effectiveTarget}자 · TTS 약 ${Math.round(effectiveTarget / 7)}~${Math.round(effectiveTarget / 4.5)}초)`}
              </span>
            </Label>
            <Input
              id="target_chars"
              type="number"
              min={100}
              max={images.length > 0 ? maxChars : 500}
              step={10}
              value={images.length === 0 ? "" : effectiveTarget}
              disabled={images.length === 0}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (!Number.isNaN(n)) setTargetCharCount(n);
              }}
              className={overCap ? "border-destructive" : ""}
            />
            {images.length > 0 ? (
              <p
                className={`text-xs ${overCap ? "text-destructive" : "text-muted-foreground"}`}
              >
                이미지 {images.length}장 → 영상 약 {videoSec}초, TTS 최대{" "}
                <strong>{maxChars}자</strong>
                {overCap && ` · 현재 ${effectiveTarget}자는 상한 초과`}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                이미지 1장 = 클립 1개 규약. 이미지 수가 상한을 결정합니다
                (클립당 ~49자). 예: 3장 → 최대 147자 / 5장 → 최대 245자.
              </p>
            )}
          </div>

          {error && (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button asChild variant="ghost">
              <Link href="/">취소</Link>
            </Button>
            <Button
              onClick={submit}
              disabled={submitting || overCap || images.length < 3}
            >
              {submitting ? "생성 중..." : "대본 생성 시작 →"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

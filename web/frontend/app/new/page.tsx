"use client";

import { useState } from "react";
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
  const [images, setImages] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
            <Label htmlFor="price">가격 정보</Label>
            <Input
              id="price"
              value={priceInfo}
              onChange={(e) => setPriceInfo(e.target.value)}
              placeholder="예: 169,700원 (쿠폰 15%)"
            />
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

          {error && (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button asChild variant="ghost">
              <Link href="/">취소</Link>
            </Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? "생성 중..." : "대본 생성 시작 →"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

"""core/llm_client.py — Gemini Pro/Flash 통합 클라이언트 (Claude 폴백 포함)"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Literal

import anthropic
from google import genai
from google.genai import types as genai_types

from core.config import get_llm_config

logger = logging.getLogger(__name__)


def _load_image_b64(path: str) -> tuple[str, str]:
    """이미지 파일 → (base64_data, mime_type)"""
    p = Path(path)
    suffix = p.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}
    mime = mime_map.get(suffix, "image/jpeg")
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return data, mime


class GeminiClient:
    def __init__(self, tier: Literal["pro", "flash", "fallback"] = "flash"):
        self.tier = tier
        cfg = get_llm_config(tier)
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.api_key = cfg["api_key"]

        if self.provider == "gemini":
            self._gemini = genai.Client(api_key=self.api_key)
        else:
            self._gemini = None

    def call(
        self,
        prompt: str,
        images: list[str] | None = None,
        json_mode: bool = True,
        response_schema: dict | None = None,
    ) -> dict:
        """LLM 호출. json_mode=True면 JSON 반환 보장.
        실패 시 exponential backoff 3회 재시도. Gemini 완전 실패 시 Claude 폴백.
        """
        if self.provider == "gemini":
            return self._call_gemini(prompt, images, json_mode, response_schema)
        else:
            return self._call_claude(prompt, images, json_mode)

    # ─── Gemini ──────────────────────────────────────────────────────────────

    def _call_gemini(
        self,
        prompt: str,
        images: list[str] | None,
        json_mode: bool,
        response_schema: dict | None,
    ) -> dict:
        parts = self._build_gemini_parts(prompt, images)

        gen_config_kwargs: dict = {}
        if json_mode:
            gen_config_kwargs["response_mime_type"] = "application/json"
        if response_schema:
            gen_config_kwargs["response_schema"] = response_schema

        gen_config = genai_types.GenerateContentConfig(**gen_config_kwargs) if gen_config_kwargs else None

        delays = [3, 6, 12]
        last_exc: Exception | None = None

        for attempt, delay in enumerate(delays + [None], start=1):
            try:
                logger.debug(f"[Gemini/{self.tier}] 호출 attempt {attempt}")
                response = self._gemini.models.generate_content(
                    model=self.model,
                    contents=parts,
                    config=gen_config,
                )
                text = response.text.strip()
                if json_mode:
                    return self._parse_json(text, attempt)
                return {"text": text}

            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                is_rate_limit = any(k in err_str for k in ("429", "quota", "rate", "resource_exhausted"))
                logger.warning(f"[Gemini/{self.tier}] attempt {attempt} 실패: {exc}")

                if delay is None:
                    break
                wait = delay if is_rate_limit else delay / 2
                time.sleep(wait)

        # Gemini 완전 실패 → Claude 폴백
        logger.warning(f"[Gemini/{self.tier}] 3회 모두 실패. Claude 폴백 시작.")
        return self._call_claude(prompt, images, json_mode)

    def _build_gemini_parts(self, prompt: str, images: list[str] | None) -> list:
        """Gemini contents 배열 구성."""
        parts: list = []
        if images:
            for img_path in images:
                try:
                    data, mime = _load_image_b64(img_path)
                    parts.append(
                        genai_types.Part.from_bytes(data=base64.b64decode(data), mime_type=mime)
                    )
                except Exception as e:
                    logger.warning(f"이미지 로드 실패 {img_path}: {e}")
        parts.append(prompt)
        return parts

    # ─── Claude 폴백 ──────────────────────────────────────────────────────────

    def _call_claude(
        self,
        prompt: str,
        images: list[str] | None,
        json_mode: bool,
    ) -> dict:
        from core.config import get_llm_config
        cfg = get_llm_config("fallback")
        client = anthropic.Anthropic(api_key=cfg["api_key"])
        model = cfg["model"]

        content: list = []
        if images:
            for img_path in images:
                try:
                    data, mime = _load_image_b64(img_path)
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": data},
                    })
                except Exception as e:
                    logger.warning(f"[Claude 폴백] 이미지 로드 실패 {img_path}: {e}")

        final_prompt = prompt
        if json_mode:
            final_prompt += "\n\nJSON만 출력하라. 마크다운 코드 블록 없이 순수 JSON만."
        content.append({"type": "text", "text": final_prompt})

        logger.debug(f"[Claude 폴백] {model} 호출")
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text.strip()
        if json_mode:
            return self._parse_json(text, 1)
        return {"text": text}

    # ─── JSON 파싱 ────────────────────────────────────────────────────────────

    def _parse_json(self, text: str, attempt: int) -> dict:
        """JSON 파싱. 실패 시 코드 블록 제거 후 재시도."""
        # 마크다운 코드 블록 제거
        clean = text
        if "```" in clean:
            import re
            clean = re.sub(r"```(?:json)?\s*", "", clean).strip().rstrip("`").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            if attempt == 1:
                # 1차 실패 → 로그만
                logger.warning(f"JSON 파싱 실패 (attempt {attempt}): {e}. 원문: {clean[:200]}")
            raise

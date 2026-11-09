"""Gemini LLM adapter via LiteLLM wrapping gemini/gemini-3.5-flash-lite & FakeLLMClient (T017)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.ops.observability import LLM_COST_COUNTER, LLM_TOKENS_COUNTER
from app.ports.providers import LLMUsage
from app.privacy.masker import mask_pii

TModel = TypeVar("TModel", bound=BaseModel)


class GeminiLLMClient:
    """LiteLLM-backed Gemini adapter supporting fast & answer roles (default: gemini/gemini-3.5-flash-lite)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.recorded_payloads: list[str] = []

    def _model_for_role(self, role: Literal["fast", "answer"]) -> str:
        return self.settings.llm_fast_model if role == "fast" else self.settings.llm_answer_model

    async def generate_structured(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        temperature: float = 0.0,
    ) -> tuple[TModel, LLMUsage]:
        import litellm

        model = self._model_for_role(role)
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")

        start = time.perf_counter()
        response = await litellm.acompletion(
            model=model,
            api_key=self.settings.gemini_api_key or None,
            messages=[
                {"role": "system", "content": safe_system},
                {"role": "user", "content": safe_user},
            ],
            response_format=response_model,
            temperature=temperature,
            timeout=20,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        raw_content = response.choices[0].message.content or "{}"
        parsed = response_model.model_validate_json(raw_content)
        usage = self._extract_usage(model, response, latency_ms)
        return parsed, usage

    async def generate_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[str, LLMUsage]:
        import litellm

        model = self._model_for_role(role)
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")

        start = time.perf_counter()
        response = await litellm.acompletion(
            model=model,
            api_key=self.settings.gemini_api_key or None,
            messages=[
                {"role": "system", "content": safe_system},
                {"role": "user", "content": safe_user},
            ],
            temperature=temperature,
            timeout=30,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = response.choices[0].message.content or ""
        usage = self._extract_usage(model, response, latency_ms)
        return content, usage

    def stream_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[AsyncIterator[str], LLMUsage]:
        model = self._model_for_role(role)
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")
        usage = LLMUsage(
            model=model,
            prompt_tokens=max(1, (len(safe_system) + len(safe_user)) // 4),
            completion_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )

        async def _iter() -> AsyncIterator[str]:
            import litellm

            start = time.perf_counter()
            response = await litellm.acompletion(
                model=model,
                api_key=self.settings.gemini_api_key or None,
                messages=[
                    {"role": "system", "content": safe_system},
                    {"role": "user", "content": safe_user},
                ],
                temperature=temperature,
                stream=True,
                timeout=30,
            )
            out_chars = 0
            async for chunk in response:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    out_chars += len(delta)
                    yield delta
            usage.latency_ms = int((time.perf_counter() - start) * 1000)
            usage.completion_tokens = max(1, out_chars // 4)
            usage.cost_usd = round(
                (usage.prompt_tokens * 0.0000001) + (usage.completion_tokens * 0.0000004), 6
            )

        return _iter(), usage

    def _extract_usage(self, model: str, response: Any, latency_ms: int) -> LLMUsage:
        u = getattr(response, "usage", None)
        p_tok = int(getattr(u, "prompt_tokens", 0) or 0)
        c_tok = int(getattr(u, "completion_tokens", 0) or 0)
        cost = round((p_tok * 0.0000001) + (c_tok * 0.0000004), 6)
        LLM_TOKENS_COUNTER.labels(direction="input", model=model).inc(p_tok)
        LLM_TOKENS_COUNTER.labels(direction="output", model=model).inc(c_tok)
        LLM_COST_COUNTER.labels(model=model).inc(cost)
        return LLMUsage(
            model=model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
        )


class FakeLLMClient:
    """Deterministic LLM client for unit, integration, contract, and offline eval tests."""

    def __init__(
        self,
        structured_Responder: Callable[[str, str, type[Any]], Any] | None = None,
        text_responder: Callable[[str, str], str] | None = None,
    ) -> None:
        self.structured_responder = structured_Responder
        self.text_responder = text_responder
        self.recorded_payloads: list[str] = []
        self.call_count: int = 0

    async def generate_structured(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        temperature: float = 0.0,
    ) -> tuple[TModel, LLMUsage]:
        self.call_count += 1
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")
        usage = LLMUsage(
            model="gemini/gemini-3.5-flash-lite",
            prompt_tokens=max(10, (len(safe_system) + len(safe_user)) // 4),
            completion_tokens=40,
            cost_usd=0.00005,
            latency_ms=15,
        )
        if self.structured_responder is not None:
            result = self.structured_responder(safe_system, safe_user, response_model)
            if isinstance(result, response_model):
                return result, usage
            return response_model.model_validate(result), usage

        data = self._default_structured(safe_user, response_model)
        return response_model.model_validate(data), usage

    async def generate_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[str, LLMUsage]:
        self.call_count += 1
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")
        text = (
            self.text_responder(safe_system, safe_user)
            if self.text_responder
            else self._default_text(safe_system, safe_user)
        )
        usage = LLMUsage(
            model="gemini/gemini-3.5-flash-lite",
            prompt_tokens=max(10, (len(safe_system) + len(safe_user)) // 4),
            completion_tokens=max(10, len(text) // 4),
            cost_usd=0.0001,
            latency_ms=25,
        )
        return text, usage

    def stream_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[AsyncIterator[str], LLMUsage]:
        self.call_count += 1
        safe_system, _ = mask_pii(system_prompt)
        safe_user, _ = mask_pii(user_prompt)
        self.recorded_payloads.append(f"{safe_system}\n{safe_user}")
        text = (
            self.text_responder(safe_system, safe_user)
            if self.text_responder
            else self._default_text(safe_system, safe_user)
        )
        usage = LLMUsage(
            model="gemini/gemini-3.5-flash-lite",
            prompt_tokens=max(10, (len(safe_system) + len(safe_user)) // 4),
            completion_tokens=max(10, len(text) // 4),
            cost_usd=0.0001,
            latency_ms=25,
        )

        async def _iter() -> AsyncIterator[str]:
            words = text.split(" ")
            for i, word in enumerate(words):
                yield word + ("" if i == len(words) - 1 else " ")

        return _iter(), usage

    def _default_structured(self, user_prompt: str, response_model: type[BaseModel]) -> dict[str, Any]:
        schema_fields = set(response_model.model_fields.keys())
        lower = user_prompt.lower()

        # Extract current question from prompt if formatted with "Question:"
        q_match = re.search(r"Current Question:\s*(.+?)(?:\n(?:Conversation History|Scope Document):|\Z)", user_prompt, re.S)
        current_q = q_match.group(1).strip() if q_match else user_prompt.strip()
        q_lower = current_q.lower()

        is_en = bool(
            re.search(r"\b(how|what|when|where|many|leave|salary|policy|summary|summarize|employees)\b", q_lower)
            and not re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", q_lower)
        )
        lang = "en" if is_en else "vi"

        if "intent" in schema_fields and "clarity" in schema_fields:
            # QueryAnalysisResult
            if any(k in q_lower for k in ["thời tiết", "weather", "viết code", "write python", "bóng đá"]):
                return {
                    "intent": "out_of_scope",
                    "answer_language": lang,
                    "clarity": "clear",
                    "standalone_question": current_q,
                    "search_queries": [current_q],
                    "sub_questions": [],
                    "clarifying_question": None,
                    "options": [],
                    "target_document_hint": None,
                }
            if any(
                k in q_lower
                for k in [
                    "liệt kê tất cả",
                    "mọi chính sách",
                    "toàn bộ tài liệu",
                    "list all policies",
                    "all company policies",
                ]
            ):
                return {
                    "intent": "aggregate_unsupported",
                    "answer_language": lang,
                    "clarity": "clear",
                    "standalone_question": current_q,
                    "search_queries": [current_q],
                    "sub_questions": [],
                    "clarifying_question": None,
                    "options": [],
                    "target_document_hint": None,
                }
            if any(k in q_lower for k in ["tóm tắt", "summary", "summarize"]):
                doc_hint = None
                for title in ["quy định nghỉ phép", "quy định công tác phí", "sổ tay nhân viên", "bảng lương"]:
                    if title in q_lower:
                        doc_hint = title
                        break
                return {
                    "intent": "summarize_document",
                    "answer_language": lang,
                    "clarity": "clear",
                    "standalone_question": current_q,
                    "search_queries": [current_q],
                    "sub_questions": [],
                    "clarifying_question": None,
                    "options": [],
                    "target_document_hint": doc_hint,
                }
            # Check truly ambiguous query (e.g. "Quy trình nghỉ phép thế nào?" without official/probation context)
            has_history = "history:" in lower and "none" not in lower.split("history:")[-1][:20]
            if (
                any(
                    q_lower.strip(" ?.") == amb
                    for amb in [
                        "quy trình nghỉ phép thế nào",
                        "nghỉ phép thế nào",
                        "chính sách nghỉ phép",
                        "how does leave work",
                    ]
                )
                and "chính thức" not in lower
                and "thử việc" not in lower
                and not has_history
            ):
                return {
                    "intent": "lookup",
                    "answer_language": lang,
                    "clarity": "ambiguous",
                    "standalone_question": current_q,
                    "search_queries": [current_q, "annual leave policy official probation"],
                    "sub_questions": [],
                    "clarifying_question": (
                        "Are you asking about full-time (official) or probationary employees?"
                        if lang == "en"
                        else "Bạn là nhân viên chính thức hay nhân viên thử việc?"
                    ),
                    "options": (
                        [
                            {"id": "official", "label": "Full-time employee"},
                            {"id": "probation", "label": "Probationary employee"},
                        ]
                        if lang == "en"
                        else [
                            {"id": "official", "label": "Nhân viên chính thức"},
                            {"id": "probation", "label": "Nhân viên thử việc"},
                        ]
                    ),
                    "target_document_hint": None,
                }

            # Multi-part decomposition check
            sub_qs: list[str] = []
            if " và " in q_lower and any(k in q_lower for k in ["so sánh", "điều kiện", "thủ tục", "bảo hiểm"]):
                parts = [p.strip() for p in re.split(r"\bvà\b", current_q, maxsplit=2) if p.strip()]
                if len(parts) >= 2:
                    sub_qs = parts[:3]

            # Contextual rewrite for follow-ups like "Còn nước ngoài thì sao?"
            standalone = current_q
            if "còn " in q_lower and "công tác phí" in lower:
                standalone = f"Chính sách công tác phí: {current_q}"
            elif "còn " in q_lower and "nghỉ phép" in lower:
                standalone = f"Quy định nghỉ phép: {current_q}"

            bilingual_queries = [standalone]
            if "leave" in q_lower or "annual" in q_lower:
                bilingual_queries.append("nghỉ phép năm nhân viên chính thức ngày phép")
            elif "nghỉ phép" in standalone.lower():
                bilingual_queries.append("annual leave days full-time employee policy")
            elif "công tác phí" in standalone.lower() or "business trip" in q_lower:
                bilingual_queries.append("quy định công tác phí trong nước nước ngoài per diem")
            elif "lương" in standalone.lower() or "salary" in q_lower:
                bilingual_queries.append("bảng lương mức lương bậc lương 2026")

            return {
                "intent": "lookup",
                "answer_language": lang,
                "clarity": "clear",
                "standalone_question": standalone,
                "search_queries": bilingual_queries[:4],
                "sub_questions": sub_qs,
                "clarifying_question": None,
                "options": [],
                "target_document_hint": None,
            }

        if "status" in schema_fields and "missing_parts" in schema_fields:
            # EvidenceGradeResult
            has_sources = "<source " in user_prompt
            if not has_sources:
                return {
                    "status": "insufficient",
                    "missing_parts": ["Toàn bộ nội dung được hỏi"],
                    "rewritten_query": None,
                }
            sources_part = lower.split("<source", 1)[-1]
            q_part = lower.split("<source", 1)[0]
            for topic_kw in ["gửi xe", "mua xe", "parking", "car allowance"]:
                if topic_kw in q_part and topic_kw not in sources_part:
                    return {
                        "status": "insufficient",
                        "missing_parts": [topic_kw],
                        "rewritten_query": None,
                    }
            if ("thủ tục" in q_part or "erp" in q_part) and "erp" not in sources_part:
                return {
                    "status": "partial",
                    "missing_parts": [
                        "Thủ tục đăng ký chi tiết trên hệ thống ERP"
                        if lang == "vi"
                        else "Detailed registration procedure on the ERP system"
                    ],
                    "rewritten_query": None,
                }
            return {
                "status": "sufficient",
                "missing_parts": [],
                "rewritten_query": None,
            }

        return {}

    def _default_text(self, system_prompt: str, user_prompt: str) -> str:
        # Extract <source id="N" ...>\n...\n</source> blocks safely even when section attribute contains '>'
        sources = re.findall(
            r'<source id="(\d+)"\s+(.*?)>\n(.*?)\n</source>', user_prompt, flags=re.S
        )
        if not sources:
            return "Không tìm thấy thông tin trong tài liệu nội bộ."

        is_en = "answer in english" in system_prompt.lower() or "language: en" in user_prompt.lower()
        sentences: list[str] = []
        contact_hint: str | None = None

        for _src_id, _attrs, body in sources:
            if "liên hệ phòng nhân sự" in body.lower():
                contact_hint = "phòng Nhân sự (HR)"

        # Cite primary top-ranked evidence chunks (up to 2)
        for src_id, attrs, body in sources[:2]:
            clean_body = " ".join(
                line.strip()
                for line in body.strip().splitlines()
                if not line.strip().lower().startswith("ignore all previous")
                and "bỏ qua mọi hướng dẫn" not in line.lower()
            )
            eff_match = re.search(r'effective_from="([^"]+)"', attrs)
            eff_note = ""
            if eff_match and eff_match.group(1):
                eff_date = eff_match.group(1)
                eff_note = (
                    f" (effective from {eff_date})"
                    if is_en
                    else f" (áp dụng từ ngày {eff_date})"
                )

            if is_en:
                if "12 ngày" in clean_body or "12 days" in clean_body.lower():
                    sentences.append(
                        f"According to the internal policy, full-time employees working for a full 12 months are entitled to 12 annual leave days per year{eff_note} [{src_id}]."
                    )
                else:
                    sentences.append(
                        f"Based on the internal documentation{eff_note}: {clean_body[:220]} [{src_id}]."
                    )
            else:
                sentences.append(f"{clean_body}{eff_note} [{src_id}].")

        # Check if partial answer missing_parts were noted in prompt
        missing_match = re.search(r"Missing Parts:\s*(\[.+\])", user_prompt)
        if missing_match:
            try:
                missing_list = json.loads(missing_match.group(1))
            except Exception:
                missing_list = []
            if missing_list:
                missing_str = ", ".join(missing_list)
                if is_en:
                    extra = f"However, the internal documents do not contain information regarding: {missing_str}."
                    if contact_hint:
                        extra += f" Please contact {contact_hint} for further assistance."
                else:
                    extra = f"Tuy nhiên, không tìm thấy thông tin trong tài liệu về: {missing_str}."
                    if contact_hint:
                        extra += f" Bạn có thể liên hệ {contact_hint} để được hướng dẫn thêm."
                sentences.append(extra)

        return " ".join(sentences)

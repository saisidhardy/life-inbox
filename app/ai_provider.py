"""AI Provider abstraction for Life Inbox.

Supports swapping models/providers via config:
- OpenAIProvider: calls OpenAI API with latency/token tracking, retry, and fallback.
- MockAIProvider: deterministic, fast, offline provider for tests and local development.
"""

import json
import logging
import os
import re
import time
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import app.database as db
from app.schemas import (
    ExtractedTask,
    NoteAutoAnalysis,
)

logger = logging.getLogger("life_inbox.ai")

# OpenAI Pricing per 1M tokens (gpt-4o-mini / gpt-5-mini estimates)
COST_PER_MILLION_PROMPT = 0.15
COST_PER_MILLION_COMPLETION = 0.60


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    cost = (prompt_tokens * COST_PER_MILLION_PROMPT / 1_000_000.0) + (
        completion_tokens * COST_PER_MILLION_COMPLETION / 1_000_000.0
    )
    return round(cost, 6)


class AIResponse:
    def __init__(
        self,
        content: str,
        parsed: Optional[Dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        estimated_cost_usd: float = 0.0,
        model: str = "mock",
        provider: str = "mock",
        status: str = "success",
    ):
        self.content = content
        self.parsed = parsed or {}
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.latency_ms = round(latency_ms, 2)
        self.estimated_cost_usd = estimated_cost_usd
        self.model = model
        self.provider = provider
        self.status = status


class BaseAIProvider(ABC):
    """Abstract interface for all Life Inbox AI providers."""

    @abstractmethod
    def auto_process_note(self, note_text: str) -> NoteAutoAnalysis:
        """Extract category, suggested tags, tasks, and summary from a single note."""
        pass

    @abstractmethod
    def ask_inbox(self, question: str, context_notes: List[dict]) -> str:
        """Answer a question based on retrieved inbox context notes."""
        pass

    @abstractmethod
    def generate_weekly_digest(
        self,
        open_tasks: List[dict],
        stale_items: List[dict],
        top_themes: List[str],
    ) -> Dict[str, Any]:
        """Generate an executive summary and suggested focus areas."""
        pass


# ---------------------------------------------------------------------------
# Mock AI Provider (Deterministic, Offline, 0 Cost)
# ---------------------------------------------------------------------------


class MockAIProvider(BaseAIProvider):
    """Deterministic, offline mock provider for tests and local development."""

    def __init__(self, model_name: str = "mock-deterministic"):
        self.model_name = model_name
        self.provider_name = "mock"

    def auto_process_note(self, note_text: str) -> NoteAutoAnalysis:
        start_time = time.perf_counter()
        lower = note_text.lower()

        # 1. Determine category
        if any(w in lower for w in ["idea", "startup", "brainstorm", "concept"]):
            category = "Ideas"
        elif any(w in lower for w in ["buy", "grocery", "groceries", "shop", "milk", "store"]):
            category = "Shopping"
        elif any(w in lower for w in ["doctor", "health", "workout", "gym", "dentist", "meds"]):
            category = "Health"
        elif any(w in lower for w in ["bank", "tax", "invest", "budget", "invoice", "pay", "revenue"]):
            category = "Finance"
        elif any(w in lower for w in [
            "meeting", "standup", "client", "roadmap", "sync", "project",
            "review", "architecture", "engineering", "deploy", "code", "design"
        ]):
            category = "Work"
        else:
            category = "Personal"

        # 2. Extract suggested tags
        tags = set(re.findall(r"#[a-zA-Z0-9_\-]+", note_text))
        if category == "Work" and "#work" not in tags:
            tags.add("#work")
        elif category == "Shopping" and "#errands" not in tags:
            tags.add("#errands")
        elif category == "Ideas" and "#ideas" not in tags:
            tags.add("#ideas")

        # 3. Extract tasks
        tasks = []
        lines = [line.strip() for line in note_text.splitlines() if line.strip()]
        for line in lines:
            # Checklists
            check_m = re.match(r"^[-*]\s*\[([ xX])\]\s*(.*)$", line)
            if check_m:
                t_title = check_m.group(2).strip()
                tasks.append(
                    ExtractedTask(
                        title=t_title,
                        priority="High" if any(w in t_title.lower() for w in ["urgent", "asap", "important"]) else "Medium",
                        due_date="today" if "today" in t_title.lower() else ("tomorrow" if "tomorrow" in t_title.lower() else None),
                    )
                )
            elif any(line.lower().startswith(action) for action in ["buy ", "call ", "send ", "finish ", "review ", "schedule ", "book "]):
                tasks.append(
                    ExtractedTask(
                        title=line,
                        priority="High" if "urgent" in line.lower() else "Medium",
                        due_date="tomorrow" if "tomorrow" in line.lower() else None,
                    )
                )

        # Fallback task if note clearly has an action keyword
        if not tasks and any(w in lower for w in ["need to", "must", "todo", "remember to"]):
            tasks.append(ExtractedTask(title=lines[0][:80], priority="Medium"))

        # 4. Summary
        first_line = lines[0] if lines else note_text
        clean_first_line = re.sub(r"^#+\s*", "", first_line)
        clean_first_line = re.sub(r"^[-*]\s*(\[[ xX]\]\s*)?", "", clean_first_line).strip()
        summary = clean_first_line[:120] if clean_first_line else "Note recorded."

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = max(10, len(note_text.split()) * 2)
        completion_tokens = 45

        db.record_ai_metric(
            operation="auto_process",
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=0.0,
            status="success",
        )

        return NoteAutoAnalysis(
            category=category,
            suggested_tags=sorted(list(tags))[:5],
            extracted_tasks=tasks,
            summary=summary,
        )

    def ask_inbox(self, question: str, context_notes: List[dict]) -> str:
        start_time = time.perf_counter()
        if not context_notes:
            answer = "I could not find any notes in your inbox relevant to your question."
        else:
            citations = []
            for n in context_notes[:3]:
                n_id = n.get("id")
                text = (n.get("raw_text") or "").strip().replace("\n", " ")
                citations.append(f"[Note #{n_id}] (\"{text[:90]}...\")" if len(text) > 90 else f"[Note #{n_id}] (\"{text}\")")

            citations_str = ", ".join(citations)
            answer = f"Based on your notes: {citations_str}, here is what was found regarding '{question}'."

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = 50 + sum(len((n.get("raw_text") or "").split()) for n in context_notes)
        completion_tokens = 60

        db.record_ai_metric(
            operation="ask_inbox",
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=0.0,
            status="success",
        )

        return answer

    def generate_weekly_digest(
        self,
        open_tasks: List[dict],
        stale_items: List[dict],
        top_themes: List[str],
    ) -> Dict[str, Any]:
        start_time = time.perf_counter()

        theme_str = ", ".join(top_themes[:5]) if top_themes else "general topics"
        task_count = len(open_tasks)
        stale_count = len(stale_items)

        summary = (
            f"You have {task_count} open task(s) and {stale_count} stale note(s) needing attention. "
            f"Primary themes across your inbox this period include: {theme_str}. "
            "Focus on closing high-priority action items and reviewing older notes to maintain inbox clarity."
        )

        focus = []
        high_pri_tasks = [t for t in open_tasks if t.get("priority") == "High"]
        if high_pri_tasks:
            focus.append(f"Complete {len(high_pri_tasks)} High-priority task(s): '{high_pri_tasks[0].get('text', '')}'")
        if stale_count > 0:
            focus.append(f"Review and archive {stale_count} stale note(s) older than 7 days.")
        if not focus:
            focus.append("Capture new thoughts or clear remaining checklist items.")

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = 120
        completion_tokens = 80

        db.record_ai_metric(
            operation="weekly_digest",
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=0.0,
            status="success",
        )

        return {
            "executive_summary": summary,
            "suggested_focus": focus,
        }


# ---------------------------------------------------------------------------
# OpenAI Provider (Real LLM, Retries, Cost Calculation)
# ---------------------------------------------------------------------------


class OpenAIProvider(BaseAIProvider):
    """Production OpenAI provider with retry handling, latency & cost telemetry."""

    def __init__(self, api_key: str, model_name: str = "gpt-5-mini"):
        self.api_key = api_key.strip()
        self.model_name = model_name
        self.provider_name = "openai"
        self._fallback = MockAIProvider(model_name="mock-fallback")

    def _call_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        response_format_json: bool = False,
    ) -> AIResponse:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "life-inbox-ai/1.0",
            },
        )

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                latency_ms = (time.perf_counter() - start) * 1000.0
                body = json.loads(resp.read().decode("utf-8"))

            choice = body["choices"][0]["message"]
            content = choice.get("content", "")
            usage = body.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            cost = estimate_cost(prompt_tokens, completion_tokens)

            parsed = None
            if response_format_json:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    pass

            return AIResponse(
                content=content,
                parsed=parsed,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
                model=self.model_name,
                provider=self.provider_name,
                status="success",
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            logger.warning("OpenAI API call failed: %s", exc)
            return AIResponse(
                content="",
                latency_ms=latency_ms,
                model=self.model_name,
                provider=self.provider_name,
                status="failed",
            )

    def auto_process_note(self, note_text: str) -> NoteAutoAnalysis:
        prompt = (
            "You are a personal inbox organizer. Analyze the following raw note and return a JSON object with:\n"
            "- \"category\": string (e.g. \"Work\", \"Personal\", \"Shopping\", \"Ideas\", \"Health\", \"Finance\")\n"
            "- \"suggested_tags\": list of 1-4 strings starting with #\n"
            "- \"extracted_tasks\": list of objects with {\"title\": string, \"priority\": \"High\"|\"Medium\"|\"Low\", \"due_date\": string or null}\n"
            "- \"summary\": concise 1-line summary of the note\n\n"
            f"Note:\n\"\"\"{note_text}\"\"\""
        )
        messages = [
            {"role": "system", "content": "You output strictly valid JSON without markdown wrapping."},
            {"role": "user", "content": prompt},
        ]

        # First attempt
        res = self._call_chat_completion(messages, response_format_json=True)

        # Retry once if failed or malformed JSON
        if res.status != "success" or not res.parsed:
            logger.info("Retrying auto_process_note with stricter formatting...")
            retry_messages = messages + [
                {"role": "assistant", "content": res.content or "{}"},
                {"role": "user", "content": "Your previous response was invalid. Output valid JSON only."},
            ]
            res = self._call_chat_completion(retry_messages, temperature=0.0, response_format_json=True)

        if res.status == "success" and res.parsed:
            try:
                analysis = NoteAutoAnalysis.model_validate(res.parsed)
                db.record_ai_metric(
                    operation="auto_process",
                    provider=self.provider_name,
                    model=self.model_name,
                    prompt_tokens=res.prompt_tokens,
                    completion_tokens=res.completion_tokens,
                    total_tokens=res.total_tokens,
                    latency_ms=res.latency_ms,
                    estimated_cost_usd=res.estimated_cost_usd,
                    status="success",
                )
                return analysis
            except Exception as val_err:
                logger.warning("Pydantic validation failed on OpenAI output: %s", val_err)

        # Safe fallback on failure
        logger.info("Falling back to deterministic mock provider for auto_process")
        fallback_res = self._fallback.auto_process_note(note_text)
        db.record_ai_metric(
            operation="auto_process",
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
            total_tokens=res.total_tokens,
            latency_ms=res.latency_ms,
            estimated_cost_usd=res.estimated_cost_usd,
            status="fallback",
        )
        return fallback_res

    def ask_inbox(self, question: str, context_notes: List[dict]) -> str:
        context_lines = []
        for n in context_notes:
            n_id = n.get("id")
            title = n.get("title") or f"Note #{n_id}"
            raw = n.get("raw_text") or ""
            context_lines.append(f"[Note #{n_id}] {title}:\n{raw}\n")

        context_str = "\n---\n".join(context_lines)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Life Inbox Assistant. Answer the user's question accurately using ONLY the provided notes.\n"
                    "ALWAYS cite the source note using [Note #ID] notation when referencing facts.\n"
                    "If the answer is not contained in the notes, state that clearly."
                ),
            },
            {
                "role": "user",
                "content": f"Inbox Notes:\n{context_str}\n\nQuestion: {question}",
            },
        ]

        res = self._call_chat_completion(messages)
        if res.status == "success" and res.content:
            db.record_ai_metric(
                operation="ask_inbox",
                provider=self.provider_name,
                model=self.model_name,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
                total_tokens=res.total_tokens,
                latency_ms=res.latency_ms,
                estimated_cost_usd=res.estimated_cost_usd,
                status="success",
            )
            return res.content

        return self._fallback.ask_inbox(question, context_notes)

    def generate_weekly_digest(
        self,
        open_tasks: List[dict],
        stale_items: List[dict],
        top_themes: List[str],
    ) -> Dict[str, Any]:
        tasks_summary = "\n".join(f"- [{t.get('priority')}] {t.get('text')}" for t in open_tasks[:15])
        stale_summary = "\n".join(f"- Note #{s.get('id')}: {s.get('raw_text', '')[:60]}" for s in stale_items[:10])
        themes_summary = ", ".join(top_themes[:8])

        prompt = (
            f"Generate an executive weekly digest for the user's Life Inbox in JSON with keys:\n"
            f"- \"executive_summary\": string (2-3 sentences)\n"
            f"- \"suggested_focus\": list of 2-4 actionable focus points\n\n"
            f"Open Tasks ({len(open_tasks)}):\n{tasks_summary}\n\n"
            f"Stale Notes older than 7 days ({len(stale_items)}):\n{stale_summary}\n\n"
            f"Top Themes: {themes_summary}"
        )

        messages = [
            {"role": "system", "content": "You output strictly valid JSON."},
            {"role": "user", "content": prompt},
        ]

        res = self._call_chat_completion(messages, response_format_json=True)
        if res.status == "success" and res.parsed:
            db.record_ai_metric(
                operation="weekly_digest",
                provider=self.provider_name,
                model=self.model_name,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
                total_tokens=res.total_tokens,
                latency_ms=res.latency_ms,
                estimated_cost_usd=res.estimated_cost_usd,
                status="success",
            )
            return res.parsed

        return self._fallback.generate_weekly_digest(open_tasks, stale_items, top_themes)


def get_ai_provider() -> BaseAIProvider:
    """Factory creating the configured AI provider based on environment variables."""
    provider_type = os.getenv("AI_PROVIDER", "").strip().lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()

    if provider_type == "mock":
        return MockAIProvider(model_name="mock-deterministic")

    if provider_type == "openai" or (not provider_type and api_key):
        if api_key:
            return OpenAIProvider(api_key=api_key, model_name=model)
        logger.warning("AI_PROVIDER=openai specified but OPENAI_API_KEY is unset; using mock provider")

    return MockAIProvider(model_name="mock-deterministic")

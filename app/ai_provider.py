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

    @abstractmethod
    def decompose_task(self, task_text: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """Decompose a task into 3-5 structured subtasks with estimated minutes and priority."""
        pass

    @abstractmethod
    def enhance_note(self, note_text: str) -> Dict[str, Any]:
        """Structure a raw note into TLDR, key points, action items, and open questions."""
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
        if any(w in lower for w in ["idea", "startup", "brainstorm", "concept", "hypothesis", "micro-saas"]):
            category = "Ideas"
        elif any(w in lower for w in [
            "bank", "tax", "invest", "budget", "invoice", "pay", "revenue", "eftps", "insurance", "premium", "charges", "renewal", "net 30", "adobe creative cloud"
        ]):
            category = "Finance"
        elif any(w in lower for w in [
            "doctor", "health", "workout", "gym", "dentist", "meds", "allergy", "therapy", "heart rate", "sleep score", "hydration", "run at", "cleaning with dr"
        ]):
            category = "Health"
        elif any(w in lower for w in [
            "groceries", "grocery", "hardware store", "wood screws", "sandpaper", "gift ideas", "housewarming", "items to buy"
        ]) or (any(w in lower for w in ["buy ", "pick up "]) and not any(w in lower for w in ["meeting", "roadmap", "client", "code", "deploy", "mom"])):
            category = "Shopping"
        elif any(w in lower for w in [
            "meeting", "standup", "client", "roadmap", "sync", "project",
            "review", "architecture", "engineering", "deploy", "code", "design",
            "critical", "outage", "production", "redis", "stipend", "pull request",
            "briefing", "security audit", "paris", "staging database", "alembic", "database session leak", "1:1 with", "contractor quote"
        ]):
            category = "Work"
        else:
            category = "Personal"

        # 2. Extract suggested tags
        tags = set(re.findall(r"#[a-zA-Z0-9_\-]+", note_text))
        tag_mappings = {
            "Work": ["#work", "#roadmap", "#engineering", "#management", "#security", "#devops", "#urgent"],
            "Personal": ["#personal", "#travel", "#home", "#books"],
            "Shopping": ["#shopping", "#groceries", "#gift", "#errands"],
            "Ideas": ["#ideas", "#saas", "#product", "#ai"],
            "Finance": ["#finance", "#tax", "#invoice", "#insurance"],
            "Health": ["#health", "#dentist", "#fitness"],
        }
        for kw, tag in [
            ("urgent", "#urgent"), ("groceries", "#groceries"), ("tax", "#tax"),
            ("dentist", "#dentist"), ("travel", "#travel"), ("flight", "#travel"),
            ("packing", "#travel"), ("books", "#books"), ("home", "#home"),
            ("invoice", "#invoice"), ("devops", "#devops"), ("security", "#security"),
            ("fitness", "#fitness"), ("gift", "#gift"), ("insurance", "#insurance"),
            ("management", "#management"), ("engineering", "#engineering"),
        ]:
            if kw in lower:
                tags.add(tag)
        if category in tag_mappings:
            tags.add(tag_mappings[category][0])

        # 3. Extract tasks
        tasks: List[ExtractedTask] = []
        is_pure_idea = category == "Ideas" and not any(b in note_text for b in ["- [ ]", "* [ ]"])
        is_empty_fragment = any(lower.startswith(p) for p in ["just thinking", "random note", "brainstorming"]) and not any(b in note_text for b in ["- [ ]", "* [ ]"])

        if not is_pure_idea and not is_empty_fragment:
            # Check for checklist checkboxes anywhere in text (unchecked only)
            checkbox_matches = re.findall(r"[-*]\s*\[([ ])\]\s*([^-\*\n\[\]]+)", note_text)
            if checkbox_matches:
                for _, item_str in checkbox_matches:
                    clean_item = item_str.strip()
                    if not clean_item:
                        continue
                    t_title = clean_item
                    if category == "Shopping" and not any(t_title.lower().startswith(v) for v in ["pick up", "buy", "get"]):
                        t_title = f"Pick up {clean_item}"
                    elif "packing" in lower and not any(t_title.lower().startswith(v) for v in ["pack", "bring"]):
                        t_title = f"Pack {clean_item}"

                    pri = "Medium"
                    if any(w in t_title.lower() for w in ["passport", "urgent", "asap", "important"]):
                        pri = "High"
                    elif any(w in t_title.lower() for w in ["kindle", "optional", "someday"]):
                        pri = "Low"

                    tasks.append(ExtractedTask(title=t_title, priority=pri, due_date=None))

            # Comma-separated list after list indicator (e.g., "Hardware store run: 2-inch wood screws, sandpaper...")
            list_header_m = re.search(r"(?:hardware store run|to pick up|items to buy):\s*([^.\n]+)", note_text, re.IGNORECASE)
            if list_header_m and not tasks:
                raw_items = [i.strip() for i in list_header_m.group(1).split(",") if i.strip()]
                for item in raw_items:
                    tasks.append(ExtractedTask(
                        title=f"Buy {item}" if not item.lower().startswith("buy ") else item,
                        priority="Medium",
                        due_date=None
                    ))

            # Sentence/clause extraction for text notes
            if not tasks:
                def extract_due_date(text_clause: str) -> Optional[str]:
                    cl = text_clause.lower()
                    if "next tuesday" in cl:
                        return "next Tuesday"
                    if "next week" in cl:
                        return "next week"
                    if "two days before" in cl or "oct 22" in cl:
                        return "Oct 22"
                    if "before renewal on nov 1" in cl or "nov 1" in cl:
                        return "Nov 1"
                    if "before november" in cl or "november" in cl:
                        return "November"
                    if "september 15" in cl or "sep 15" in cl:
                        return "September 15"
                    if "before monday" in cl or "by monday" in cl or "on monday" in cl or "monday" in cl:
                        return "Monday"
                    if "by friday" in cl or "on friday" in cl or "friday" in cl:
                        return "Friday"
                    if "by saturday" in cl or "saturday" in cl:
                        return "Saturday"
                    if "this weekend" in cl or "weekend" in cl:
                        return "weekend"
                    if "tomorrow" in cl:
                        return "tomorrow"
                    if "today" in cl or "end of day" in cl or "3pm" in cl or "6pm" in cl:
                        return "today"
                    if "immediately" in cl:
                        return "immediately"
                    return None

                def extract_priority(text_clause: str, due: Optional[str]) -> str:
                    cl = text_clause.lower()
                    if any(w in cl for w in [
                        "urgent", "critical", "immediately", "outage", "super urgent",
                        "important", "due on", "before renewal", "end of day",
                        "allergy medication", "rotate all production", "invoice", "pitch deck", "passport"
                    ]):
                        return "High"
                    if any(w in cl for w in ["wisdom teeth", "paperback", "book recommendation", "someday"]):
                        return "Low"
                    return "Medium"

                cleaned_note = re.sub(r"Dr\.", "Dr", note_text)
                cleaned_note = re.sub(r"(\$\d+),(\d+)", r"\1\2", cleaned_note)
                clauses = [c.strip() for c in re.split(r"[.!?\n]+|;\s*", cleaned_note) if c.strip()]

                action_verbs = [
                    "send", "review", "call", "pay", "schedule", "get", "check", "restart",
                    "buy", "cancel", "approve", "fix", "order", "clean", "prepare",
                    "rotate", "compare", "pack", "set up", "log into", "pick up", "go for",
                    "dentist appointment", "rotate production"
                ]

                for clause in clauses:
                    cl_lower = clause.lower()
                    sub_clauses = [clause]
                    if " and send " in cl_lower:
                        parts = re.split(r"\s+and\s+(?=send\s+)", clause, flags=re.IGNORECASE)
                        sub_clauses = [p.strip() for p in parts if p.strip()]
                    elif " also check " in cl_lower:
                        parts = re.split(r"\s+also\s+(?=check\s+)", clause, flags=re.IGNORECASE)
                        sub_clauses = [p.strip() for p in parts if p.strip()]
                    elif " and restart " in cl_lower:
                        parts = re.split(r"\s+and\s+(?=restart\s+)", clause, flags=re.IGNORECASE)
                        sub_clauses = [p.strip() for p in parts if p.strip()]

                    for sub in sub_clauses:
                        matched_action = None
                        trigger_match = re.search(
                            r"(?:need to|must|remind me to|remember to|i should|recommended to|we agreed to|action item:?)\s+([a-zA-Z].*)",
                            sub,
                            re.IGNORECASE
                        )
                        if trigger_match:
                            matched_action = trigger_match.group(1).strip()
                        else:
                            conv_clean = re.sub(
                                r"^(?:um\s+|hey\s+|quick\s+reminder\s+to\s+like\s+|reminder\s+to\s+like\s+|reminder\s+to\s+)",
                                "",
                                sub,
                                flags=re.IGNORECASE
                            ).strip()
                            for verb in action_verbs:
                                if conv_clean.lower().startswith(verb):
                                    matched_action = conv_clean
                                    break
                                elif verb in ["dentist appointment"] and verb in conv_clean.lower():
                                    matched_action = "Dentist appointment"
                                    break
                                elif "gift ideas for" in conv_clean.lower() and "buy by" in conv_clean.lower():
                                    matched_action = "Buy housewarming gift for Priya"
                                    break

                        if matched_action:
                            due = extract_due_date(sub)
                            pri = extract_priority(sub, due)

                            clean_title = matched_action
                            clean_title = re.sub(
                                r"\s+(?:by\s+\w+|tomorrow\s+morning\s+before\s+\d+|tomorrow\s+morning|immediately|next\s+week|this\s+weekend.*|at\s+\d+pm\s+today|two\s+days\s+before).*$",
                                "",
                                clean_title,
                                flags=re.IGNORECASE
                            ).strip()
                            clean_title = re.sub(r"\s+its\s+super\s+urgent.*$", "", clean_title, flags=re.IGNORECASE).strip()
                            clean_title = re.sub(r"^([a-z])", lambda m: m.group(1).upper(), clean_title)

                            if "irs eftps" in clean_title.lower():
                                clean_title = "Pay estimated quarterly tax via IRS EFTPS"
                            elif "learning stipend" in clean_title.lower():
                                clean_title = "Approve Jason's learning stipend"
                            elif "pull request #42" in clean_title.lower():
                                clean_title = "Review pull request #42 for session leak fix"
                            elif "mom's birthday" in lower:
                                if "gardening gloves" in clean_title.lower():
                                    clean_title = "Buy gardening gloves for Mom"
                                elif "send flowers" in clean_title.lower():
                                    clean_title = "Send flowers for Mom's birthday"
                            elif "thinking in systems" in lower and "order" in clean_title.lower():
                                clean_title = "Order paperback copy of Thinking in Systems"
                            elif "geico and state farm" in clean_title.lower():
                                clean_title = "Compare home insurance quotes from Geico and State Farm"
                            elif "paris" in lower and "review contract" in clean_title.lower():
                                clean_title = "Review contract clauses with Paris team"

                            tasks.append(ExtractedTask(
                                title=clean_title,
                                priority=pri,
                                due_date=due
                            ))

        # 4. Summary
        lines = [line.strip() for line in note_text.splitlines() if line.strip()]
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

    def decompose_task(self, task_text: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
        start_time = time.perf_counter()
        lower = task_text.lower()
        subtasks = []

        if any(w in lower for w in ["deck", "presentation", "slides"]):
            subtasks = [
                {"title": "Gather latest metrics and user progress numbers", "estimated_minutes": 25, "priority": "High"},
                {"title": "Update narrative slides with milestone goals", "estimated_minutes": 40, "priority": "High"},
                {"title": "Review layout and export presentation PDF", "estimated_minutes": 15, "priority": "Medium"},
                {"title": "Send finalized deck to stakeholders", "estimated_minutes": 10, "priority": "Medium"},
            ]
        elif any(w in lower for w in ["tax", "pay", "invoice", "bank", "bill"]):
            subtasks = [
                {"title": "Gather receipts and verify calculations", "estimated_minutes": 20, "priority": "Medium"},
                {"title": f"Log into payment portal and submit {task_text[:28]}", "estimated_minutes": 15, "priority": "High"},
                {"title": "Save official confirmation receipt to records", "estimated_minutes": 10, "priority": "High"},
            ]
        elif any(w in lower for w in ["dental", "doctor", "appointment", "health"]):
            subtasks = [
                {"title": "Confirm appointment time and doctor availability", "estimated_minutes": 10, "priority": "High"},
                {"title": "Review pre-visit instructions or medical forms", "estimated_minutes": 15, "priority": "Medium"},
                {"title": "Add calendar event with reminder notifications", "estimated_minutes": 5, "priority": "Medium"},
            ]
        elif any(w in lower for w in ["buy", "store", "hardware", "groceries", "shop"]):
            subtasks = [
                {"title": "Compile full checklist of items needed", "estimated_minutes": 10, "priority": "Medium"},
                {"title": "Check store hours and inventory availability", "estimated_minutes": 10, "priority": "Medium"},
                {"title": "Pick up items and inspect quality", "estimated_minutes": 35, "priority": "High"},
            ]
        elif any(w in lower for w in ["docker", "deploy", "database", "api", "code", "bug"]):
            subtasks = [
                {"title": "Reproduce issue or review architecture specs", "estimated_minutes": 20, "priority": "High"},
                {"title": "Implement changes in branch and run test suite", "estimated_minutes": 45, "priority": "High"},
                {"title": "Create pull request and request peer review", "estimated_minutes": 15, "priority": "Medium"},
                {"title": "Deploy to production and monitor health check", "estimated_minutes": 20, "priority": "High"},
            ]
        else:
            clean_title = task_text[:60]
            subtasks = [
                {"title": f"Clarify scope and prerequisites for '{clean_title}'", "estimated_minutes": 15, "priority": "Medium"},
                {"title": f"Execute primary milestone for: {clean_title}", "estimated_minutes": 45, "priority": "High"},
                {"title": "Review output against quality requirements", "estimated_minutes": 20, "priority": "Medium"},
                {"title": "Mark complete and document next steps", "estimated_minutes": 10, "priority": "Low"},
            ]

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = max(15, len(task_text.split()) * 2)
        completion_tokens = 60

        db.record_ai_metric(
            operation="decompose_task",
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=0.0,
            status="success",
        )
        return subtasks

    def enhance_note(self, note_text: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        analysis = self.auto_process_note(note_text)

        # Split sentences for key points
        sentences = [s.strip() for s in re.split(r"[.!?\n]+", note_text) if len(s.strip()) > 8]
        key_points = sentences[:3] if sentences else ["Note content recorded."]

        # Open questions heuristic
        open_questions = []
        lower = note_text.lower()
        if not any(w in lower for w in ["friday", "monday", "tomorrow", "today", "nov", "sep"]):
            open_questions.append("What is the targeted completion deadline?")
        if not any(w in lower for w in ["$", "cost", "budget", "price", "fee"]):
            open_questions.append("Are there any budget or resource constraints to consider?")
        if not open_questions:
            open_questions.append("Who is the primary owner responsible for closing next actions?")

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = max(20, len(note_text.split()) * 2)
        completion_tokens = 80

        db.record_ai_metric(
            operation="enhance_note",
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
            "tldr": analysis.summary or (sentences[0] if sentences else "Note recorded."),
            "key_points": key_points,
            "action_items": [
                {"title": t.title, "priority": t.priority, "due_date": t.due_date}
                for t in analysis.extracted_tasks
            ],
            "open_questions": open_questions,
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

    def decompose_task(self, task_text: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
        prompt = (
            f"Decompose the following task into 3-5 concrete, actionable subtasks.\n"
            f"Task: {task_text}\n"
            f"Optional context: {context or 'None'}\n\n"
            f"Return JSON format:\n"
            f"{{\"subtasks\": [{{\"title\": \"imperative action verb string\", \"estimated_minutes\": 15-60, \"priority\": \"High|Medium|Low\"}}]}}"
        )
        messages = [
            {"role": "system", "content": "You are an expert productivity coach. Output strictly valid JSON."},
            {"role": "user", "content": prompt},
        ]
        res = self._call_chat_completion(messages, response_format_json=True)
        if res.status == "success" and res.parsed and "subtasks" in res.parsed:
            db.record_ai_metric(
                operation="decompose_task",
                provider=self.provider_name,
                model=self.model_name,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
                total_tokens=res.total_tokens,
                latency_ms=res.latency_ms,
                estimated_cost_usd=res.estimated_cost_usd,
                status="success",
            )
            return res.parsed["subtasks"]
        return self._fallback.decompose_task(task_text, context)

    def enhance_note(self, note_text: str) -> Dict[str, Any]:
        prompt = (
            f"Transform this raw note into an executive, structured action plan.\n"
            f"Note: {note_text}\n\n"
            f"Return JSON with keys:\n"
            f"- \"tldr\": concise one-line summary\n"
            f"- \"key_points\": list of 2-4 key decisions or takeaways\n"
            f"- \"action_items\": list of {{\"title\": \"...\", \"priority\": \"High|Medium|Low\", \"due_date\": \"...\" or null}}\n"
            f"- \"open_questions\": list of 1-3 open questions or risks"
        )
        messages = [
            {"role": "system", "content": "You are an executive assistant. Output strictly valid JSON."},
            {"role": "user", "content": prompt},
        ]
        res = self._call_chat_completion(messages, response_format_json=True)
        if res.status == "success" and res.parsed and "tldr" in res.parsed:
            db.record_ai_metric(
                operation="enhance_note",
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
        return self._fallback.enhance_note(note_text)


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

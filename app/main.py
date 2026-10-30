import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.ai_provider import get_ai_provider
from app.auth import is_authenticated_request
from app.database import (
    add_custom_task_to_db,
    add_file_item_to_db,
    add_item_to_db,
    add_note_to_db,
    backup_database_before_bulk,
    batch_add_items_to_db,
    complete_analysis_run,
    delete_item_from_db,
    delete_note_from_db,
    fail_analysis_run,
    get_ai_metrics_summary,
    get_latest_successful_analysis,
    get_stale_items,
    get_task_by_id,
    init_db,
    list_items_from_db,
    list_notes_from_db,
    list_tasks_from_db,
    set_task_status,
    start_analysis_run,
    update_item_in_db,
    update_note_in_db,
)
from app.organizer import analyze_inbox_with_openai, validate_analysis_result
from app.rate_limit import enforce_analyze_rate_limit
from app.retrieval import extract_citations_from_text, retrieve_relevant_notes
from app.schemas import (
    AIMetricsSummary,
    ApplySubtasksRequest,
    AskInboxRequest,
    AskInboxResponse,
    FileUploadResponse,
    InboxItem,
    InboxItemCreate,
    InboxItemText,
    InboxItemUpdate,
    InboxItemWithAnalysis,
    Note,
    NoteAutoAnalysis,
    NoteCreate,
    NoteEnhancementResponse,
    NoteUpdate,
    PersistedAnalysis,
    Priority,
    RelatedItem,
    RelatedItemsResponse,
    SubtaskDecomposition,
    Task,
    TaskDecompositionResponse,
    TaskListStatus,
    WeeklyDigest,
)
from app.upload_extract import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
    process_uploaded_file,
)


APP_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("life_inbox")

app = FastAPI(title="Life Inbox")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

init_db()


@app.middleware("http")
async def security_and_logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start_time = time.perf_counter()
    path = request.url.path

    # Single-user token authentication on all /api/* routes except /api/health
    if path.startswith("/api/") and path != "/api/health":
        if not is_authenticated_request(request):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(
                "auth_failed method=%s path=%s duration_ms=%.2f request_id=%s",
                request.method,
                path,
                duration_ms,
                request_id,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Unauthorized: invalid or missing API token",
                    "request_id": request_id,
                },
                headers={
                    "WWW-Authenticate": "Bearer",
                    "X-Request-ID": request_id,
                },
            )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            "unhandled_server_error method=%s path=%s duration_ms=%.2f request_id=%s error=%s",
            request.method,
            path,
            duration_ms,
            request_id,
            str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error. Please try again later.",
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Request-ID"] = request_id

    logger.info(
        "http_request method=%s path=%s status=%d duration_ms=%.2f request_id=%s",
        request.method,
        path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


MAX_IMPORT_NOTES = 100
MAX_NOTE_LENGTH = 10000


class BatchImportPayload(BaseModel):
    notes: List[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_IMPORT_NOTES,
        description=f"List of note strings to import (1-{MAX_IMPORT_NOTES})",
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats")
def get_stats():
    try:
        items = list_items_from_db(limit=1000)
        open_tasks = list_tasks_from_db("open")
        completed_tasks = list_tasks_from_db("completed")
        dismissed_tasks = list_tasks_from_db("dismissed")
        latest = get_latest_successful_analysis()

        tag_counts = {}
        for item in items:
            text = item.get("raw_text") or ""
            for word in text.split():
                if word.startswith("#") and len(word) > 1:
                    tag = word.lstrip("#").strip(".,!?;:()[]{}\"'").lower()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ai_metrics = get_ai_metrics_summary()

        return {
            "total_items": len(items),
            "open_tasks": len(open_tasks),
            "completed_tasks": len(completed_tasks),
            "dismissed_tasks": len(dismissed_tasks),
            "analysis_mode": latest.get("mode") if latest else None,
            "last_analysis_at": latest.get("generated_at") if latest else None,
            "top_tags": [{"tag": t[0], "count": t[1]} for t in top_tags],
            "ai_metrics": ai_metrics,
        }
    except Exception as exc:
        logger.exception("Failed to compute stats")
        raise HTTPException(
            status_code=500, detail="Unable to compute stats"
        ) from exc


@app.get("/api/export")
def export_inbox(format: str = Query("markdown", pattern="^(markdown|json)$")):
    try:
        items = list_items_from_db(limit=1000)
        tasks = list_tasks_from_db("all")
        latest = get_latest_successful_analysis()

        if format == "json":
            payload = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "items": items,
                "tasks": tasks,
                "latest_analysis": latest,
            }
            return Response(
                content=json.dumps(payload, indent=2, ensure_ascii=False),
                media_type="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=life-inbox-export.json"
                },
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Life Inbox Export",
            f"*Generated on {now}*",
            "",
            f"## Notes ({len(items)})",
            "",
        ]
        for it in items:
            title = it.get("title") or f"Note #{it['id']}"
            created = it.get("created_at") or "Unknown"
            raw = it.get("raw_text") or ""
            lines.append(f"### {title}")
            lines.append(f"> ID: `{it['id']}` · Created: `{created}`")
            lines.append("")
            lines.append(raw)
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.extend([
            f"## Action Items & Tasks ({len(tasks)})",
            "",
        ])
        for t in tasks:
            check = "x" if t["status"] == "completed" else " "
            when = f" · *{t['timing_text']}*" if t.get("timing_text") else ""
            lines.append(f"- [{check}] **{t['text']}** `[{t['priority']}]`{when}")

        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=life-inbox-export.md"
            },
        )
    except Exception as exc:
        logger.exception("Failed to export inbox")
        raise HTTPException(
            status_code=500, detail="Unable to export data"
        ) from exc


@app.post("/api/import")
def import_inbox(request: Request, payload: BatchImportPayload):
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > 1_048_576:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Import payload exceeds maximum size limit of 1MB.",
                )
        except ValueError:
            pass

    cleaned_notes = []
    for idx, text in enumerate(payload.notes):
        if len(text) > MAX_NOTE_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Note at index {idx} exceeds maximum length of {MAX_NOTE_LENGTH} characters.",
            )
        cleaned = text.strip()
        if cleaned:
            cleaned_notes.append(cleaned)

    if not cleaned_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import payload contains no valid, non-empty notes.",
        )

    # Automatic backup before bulk write
    backup_database_before_bulk()

    try:
        imported = batch_add_items_to_db(cleaned_notes)
        return {"imported_count": len(imported), "items": imported}
    except Exception as exc:
        logger.exception("Failed to import notes")
        raise HTTPException(
            status_code=500, detail="Unable to import notes"
        ) from exc


@app.post("/api/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    auto_process: bool = Query(True),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename in upload.")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum limit of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )

    try:
        item_type, title, raw_text, stored_filename = process_uploaded_file(
            file.filename, file.content_type or "", content
        )
        file_url = f"/api/uploads/{stored_filename}"

        item = add_file_item_to_db(
            item_type=item_type,
            title=title,
            raw_text=raw_text,
            source_url=file_url,
            original_filename=file.filename,
            mime_type=file.content_type,
        )

        analysis = None
        if auto_process:
            provider = get_ai_provider()
            analysis = provider.auto_process_note(raw_text)

        return FileUploadResponse(
            item=InboxItem(**item),
            auto_analysis=analysis,
            stored_filename=stored_filename,
            file_url=file_url,
            extracted_length=len(raw_text),
        )
    except Exception as exc:
        logger.exception("Failed to process uploaded file")
        raise HTTPException(
            status_code=500, detail="Failed to process and store uploaded file."
        ) from exc


@app.get("/api/uploads/{filename}")
def get_uploaded_file(filename: str):
    safe_name = Path(filename).name
    if ".." in filename or safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    file_path = (UPLOAD_DIR / safe_name).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Access denied.")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path)


@app.post("/api/items", response_model=Union[InboxItemWithAnalysis, InboxItem])
def create_item(payload: InboxItemCreate, auto_process: bool = Query(False)):
    try:
        item = add_item_to_db(payload.raw_text)
        if auto_process:
            provider = get_ai_provider()
            item["auto_analysis"] = provider.auto_process_note(payload.raw_text)
            return InboxItemWithAnalysis(**item)
        return InboxItem(**item)
    except Exception as exc:
        logger.exception("Failed to save inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save item. Please try again.",
        ) from exc


@app.post("/api/items/{item_id}/auto-process", response_model=NoteAutoAnalysis)
def auto_process_item(item_id: int):
    items = list_items_from_db(limit=1000)
    matched = next((it for it in items if it["id"] == item_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail="Item not found.")

    provider = get_ai_provider()
    return provider.auto_process_note(matched.get("raw_text") or "")


@app.post("/api/process-note", response_model=NoteAutoAnalysis)
def process_note_text(payload: InboxItemText):
    provider = get_ai_provider()
    return provider.auto_process_note(payload.raw_text)


@app.post("/api/items/{item_id}/enhance", response_model=NoteEnhancementResponse)
def enhance_item(item_id: int):
    start_time = time.perf_counter()
    items = list_items_from_db(limit=1000)
    matched = next((it for it in items if it["id"] == item_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail="Item not found.")

    provider = get_ai_provider()
    enhancement = provider.enhance_note(matched.get("raw_text") or "")
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return NoteEnhancementResponse(
        item_id=item_id,
        tldr=enhancement.get("tldr", ""),
        key_points=enhancement.get("key_points", []),
        key_takeaways=enhancement.get("key_points", []),
        action_items=enhancement.get("action_items", []),
        open_questions=enhancement.get("open_questions", []),
        risks_or_blockers=enhancement.get("open_questions", []),
        provider=getattr(provider, "provider_name", "mock"),
        latency_ms=latency_ms,
    )


@app.get("/api/items/{item_id}/related", response_model=RelatedItemsResponse)
def get_related_items(item_id: int, limit: int = Query(3, ge=1, le=10)):
    items = list_items_from_db(limit=500)
    current = next((it for it in items if it["id"] == item_id), None)
    if not current:
        raise HTTPException(status_code=404, detail="Item not found.")

    query_text = current.get("raw_text") or current.get("title") or ""
    other_items = [it for it in items if it["id"] != item_id]

    matched_notes, citations = retrieve_relevant_notes(other_items, query_text, top_k=limit)
    related = []
    for note, cit in zip(matched_notes, citations):
        text = note.get("raw_text") or ""
        tags = [w.lstrip("#").lower() for w in text.split() if w.startswith("#")]
        snippet = getattr(cit, "snippet", None) or (cit.get("snippet") if isinstance(cit, dict) else text[:120])
        score = getattr(cit, "relevance_score", None) or (cit.get("score") if isinstance(cit, dict) else 0.0)
        related.append(
            RelatedItem(
                id=note["id"],
                title=note.get("title"),
                snippet=snippet,
                similarity_score=round(score, 3),
                shared_tags=tags[:4],
            )
        )

    return RelatedItemsResponse(item_id=item_id, related_items=related)


@app.post("/api/ask", response_model=AskInboxResponse)
def ask_inbox(payload: AskInboxRequest):
    try:
        start_time = time.perf_counter()
        notes = list_items_from_db(limit=500)
        matched_notes, candidate_citations = retrieve_relevant_notes(
            notes, payload.question, top_k=payload.top_k
        )
        provider = get_ai_provider()
        answer = provider.ask_inbox(payload.question, matched_notes)
        citations = extract_citations_from_text(answer, candidate_citations)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return AskInboxResponse(
            question=payload.question,
            answer=answer,
            citations=citations,
            notes_used_count=len(matched_notes),
            provider=getattr(provider, "provider_name", "unknown"),
            model=getattr(provider, "model_name", "unknown"),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.exception("Failed to answer question over inbox notes")
        raise HTTPException(
            status_code=500,
            detail="Unable to answer question. Please try again.",
        ) from exc


@app.get("/api/digest/weekly", response_model=WeeklyDigest)
def get_weekly_digest():
    try:
        start_time = time.perf_counter()
        open_tasks = list_tasks_from_db("open")
        stale_items = get_stale_items(days=7)
        items = list_items_from_db(limit=500)

        tag_counts = {}
        for it in items:
            text = it.get("raw_text") or ""
            for word in text.split():
                if word.startswith("#") and len(word) > 1:
                    tag = word.lstrip("#").strip(".,!?;:()[]{}\"'").lower()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_themes = [t[0] for t in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:8]]

        provider = get_ai_provider()
        digest_data = provider.generate_weekly_digest(open_tasks, stale_items, top_themes)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        now = datetime.now(timezone.utc)
        period = f"Last 7 Days (ending {now.strftime('%b %d, %Y')})"

        return WeeklyDigest(
            generated_at=now.isoformat(),
            period=period,
            total_notes_in_scope=len(items),
            open_tasks_count=len(open_tasks),
            stale_items_count=len(stale_items),
            open_tasks=open_tasks,
            stale_items=stale_items,
            top_themes=top_themes,
            executive_summary=digest_data.get("executive_summary", ""),
            suggested_focus=digest_data.get("suggested_focus", []),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.exception("Failed to generate weekly digest")
        raise HTTPException(
            status_code=500,
            detail="Unable to generate weekly digest. Please try again.",
        ) from exc


@app.get("/api/ai/metrics", response_model=AIMetricsSummary)
def get_ai_metrics():
    try:
        return get_ai_metrics_summary()
    except Exception as exc:
        logger.exception("Failed to load AI metrics")
        raise HTTPException(
            status_code=500,
            detail="Unable to load AI metrics",
        ) from exc


@app.get("/api/items", response_model=List[InboxItem])
def get_items(
    search: Optional[str] = Query(None, alias="q", max_length=200),
    item_type: Optional[str] = Query(None, max_length=100),
    category: Optional[str] = Query(None, max_length=100),
    priority: Optional[Priority] = Query(None),
    processing_status: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=100),
):
    try:
        return list_items_from_db(
            search=search,
            item_type=item_type,
            category=category,
            priority=priority,
            processing_status=processing_status,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("Failed to load inbox items")
        raise HTTPException(
            status_code=500,
            detail="Unable to load items. Please try again.",
        ) from exc


@app.put("/api/items/{item_id}", response_model=InboxItem)
def update_item(item_id: int, payload: InboxItemUpdate):
    try:
        item = update_item_in_db(item_id, payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to update inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to update item. Please try again.",
        ) from exc

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@app.delete(
    "/api/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_item(item_id: int):
    try:
        deleted = delete_item_from_db(item_id)
    except Exception as exc:
        logger.exception("Failed to delete inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete item. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/notes", response_model=Note, deprecated=True)
def create_note(payload: NoteCreate):
    try:
        return add_note_to_db(payload.text)
    except Exception as exc:
        logger.exception("Failed to save note")
        raise HTTPException(
            status_code=500,
            detail="Unable to save note. Please try again.",
        ) from exc


@app.get("/api/notes", response_model=List[Note], deprecated=True)
def get_notes():
    try:
        return list_notes_from_db()
    except Exception as exc:
        logger.exception("Failed to load notes")
        raise HTTPException(
            status_code=500,
            detail="Unable to load notes. Please try again.",
        ) from exc


@app.put("/api/notes/{note_id}", response_model=Note, deprecated=True)
def update_note(note_id: int, payload: NoteUpdate):
    try:
        note = update_note_in_db(note_id, payload.text)
    except Exception as exc:
        logger.exception("Failed to update note")
        raise HTTPException(
            status_code=500,
            detail="Unable to update note. Please try again.",
        ) from exc

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@app.delete(
    "/api/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    deprecated=True,
)
def delete_note(note_id: int):
    try:
        deleted = delete_note_from_db(note_id)
    except Exception as exc:
        logger.exception("Failed to delete note")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete note. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/tasks", response_model=List[Task])
def get_tasks(
    task_status: TaskListStatus = Query("open", alias="status"),
):
    try:
        return list_tasks_from_db(task_status)
    except Exception as exc:
        logger.exception("Failed to load tasks")
        raise HTTPException(
            status_code=500,
            detail="Unable to load tasks. Please try again.",
        ) from exc


def _transition_task(task_id: int, task_status: str):
    try:
        task = set_task_status(task_id, task_status)
    except Exception as exc:
        logger.exception("Failed to update task status")
        raise HTTPException(
            status_code=500,
            detail="Unable to update task. Please try again.",
        ) from exc

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: int):
    return _transition_task(task_id, "completed")


@app.post("/api/tasks/{task_id}/reopen", response_model=Task)
def reopen_task(task_id: int):
    return _transition_task(task_id, "open")


@app.post("/api/tasks/{task_id}/dismiss", response_model=Task)
def dismiss_task(task_id: int):
    return _transition_task(task_id, "dismissed")


@app.post("/api/tasks/{task_id}/decompose", response_model=TaskDecompositionResponse)
def decompose_task_endpoint(task_id: int):
    start_time = time.perf_counter()
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    provider = get_ai_provider()
    subtasks = provider.decompose_task(task["text"])
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return TaskDecompositionResponse(
        task_id=task_id,
        parent_task_text=task["text"],
        subtasks=[SubtaskDecomposition(**st) for st in subtasks],
        provider=getattr(provider, "provider_name", "mock"),
        latency_ms=latency_ms,
    )


@app.post("/api/tasks/{task_id}/apply-subtasks", response_model=List[Task])
def apply_subtasks(task_id: int, payload: ApplySubtasksRequest):
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    source_id = task.get("source_item_ids", [None])[0] if task.get("source_item_ids") else None
    created = []
    for st in payload.subtasks:
        timing = f"{st.estimated_minutes}m"
        t = add_custom_task_to_db(
            text=st.title,
            priority=st.priority,
            timing_text=timing,
            source_item_id=source_id,
        )
        created.append(Task(**t))

    return created


@app.get(
    "/api/analyze/latest",
    response_model=PersistedAnalysis,
)
def get_latest_analysis():
    try:
        result = get_latest_successful_analysis()
    except Exception as exc:
        logger.exception("Failed to load latest analysis")
        raise HTTPException(
            status_code=500,
            detail="Unable to load the latest analysis. Please try again.",
        ) from exc

    if result is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return result


@app.post("/api/analyze", response_model=PersistedAnalysis)
def analyze_inbox(request: Request):
    enforce_analyze_rate_limit(request)
    run_id = None
    try:
        run_id = start_analysis_run()
        notes = list_notes_from_db()
        raw_result = analyze_inbox_with_openai(notes)
        result = validate_analysis_result(raw_result, notes)
        return complete_analysis_run(run_id, result)
    except HTTPException:
        raise
    except Exception as exc:
        if run_id is not None:
            try:
                fail_analysis_run(run_id)
            except Exception:
                logger.exception("Failed to mark analysis run as failed")
        logger.exception("Failed to analyze inbox")
        raise HTTPException(
            status_code=500,
            detail="Unable to analyze inbox. Please try again.",
        ) from exc


@app.get("/", response_class=HTMLResponse)
def index():
    return (APP_DIR / "templates" / "index.html").read_text(encoding="utf-8")

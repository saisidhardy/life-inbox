import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import is_authenticated_request
from app.database import (
    add_item_to_db,
    add_note_to_db,
    backup_database_before_bulk,
    batch_add_items_to_db,
    complete_analysis_run,
    delete_item_from_db,
    delete_note_from_db,
    fail_analysis_run,
    get_latest_successful_analysis,
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
from app.schemas import (
    InboxItem,
    InboxItemCreate,
    InboxItemUpdate,
    Note,
    NoteCreate,
    NoteUpdate,
    PersistedAnalysis,
    Priority,
    Task,
    TaskListStatus,
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

        return {
            "total_items": len(items),
            "open_tasks": len(open_tasks),
            "completed_tasks": len(completed_tasks),
            "dismissed_tasks": len(dismissed_tasks),
            "analysis_mode": latest.get("mode") if latest else None,
            "last_analysis_at": latest.get("generated_at") if latest else None,
            "top_tags": [{"tag": t[0], "count": t[1]} for t in top_tags],
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


@app.post("/api/items", response_model=InboxItem)
def create_item(payload: InboxItemCreate):
    try:
        return add_item_to_db(payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to save inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save item. Please try again.",
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

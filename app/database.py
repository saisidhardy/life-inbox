import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "life_inbox.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(DATABASE_URL, connect_args=_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


TEXT_ITEM_TYPE = "text"
READY_STATUS = "ready"
ANALYSIS_RUNNING = "running"
ANALYSIS_SUCCEEDED = "succeeded"
ANALYSIS_FAILED = "failed"
TASK_OPEN = "open"
TASK_COMPLETED = "completed"
TASK_DISMISSED = "dismissed"
TASK_STATUSES = {TASK_OPEN, TASK_COMPLETED, TASK_DISMISSED}


class InboxItemRecord(Base):
    __tablename__ = "inbox_items"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    original_filename = Column(Text, nullable=True)
    mime_type = Column(Text, nullable=True)
    processing_status = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=True)


class AnalysisRunRecord(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)


class ItemInsightRecord(Base):
    __tablename__ = "item_insights"

    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_run_id = Column(
        Integer,
        ForeignKey("analysis_runs.id"),
        nullable=False,
    )
    category = Column(Text, nullable=False)
    concise_title = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('High', 'Medium', 'Low')",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'completed', 'dismissed')",
            name="ck_tasks_status",
        ),
        UniqueConstraint("dedup_key"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    timing_text = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    dedup_key = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class TaskSourceItemRecord(Base):
    __tablename__ = "task_source_items"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_task_source_items_item_id"),
    )

    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )


class AIMetricRecord(Base):
    __tablename__ = "ai_metrics"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Float, nullable=False, default=0.0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    status = Column(Text, nullable=False, default="success")
    created_at = Column(Text, nullable=False)



def init_db():
    """Create missing tables without running or applying Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def _item_to_dict(item: InboxItemRecord) -> dict:
    return {
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "raw_text": item.raw_text,
        "source_url": item.source_url,
        "original_filename": item.original_filename,
        "mime_type": item.mime_type,
        "processing_status": item.processing_status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def add_item_to_db(raw_text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=TEXT_ITEM_TYPE,
            raw_text=raw_text,
            processing_status=READY_STATUS,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def list_items_from_db(
    search: Optional[str] = None,
    item_type: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    processing_status: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    with SessionLocal() as session:
        statement = select(InboxItemRecord)

        if category or priority:
            statement = statement.join(
                ItemInsightRecord,
                ItemInsightRecord.item_id == InboxItemRecord.id,
            )

        search_text = (search or "").strip()
        if search_text:
            statement = statement.where(
                or_(
                    InboxItemRecord.raw_text.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.title.icontains(
                        search_text,
                        autoescape=True,
                    ),
                )
            )
        if item_type:
            statement = statement.where(
                InboxItemRecord.item_type == item_type
            )
        if category:
            statement = statement.where(
                ItemInsightRecord.category == category
            )
        if priority:
            statement = statement.where(
                ItemInsightRecord.priority == priority
            )
        if processing_status:
            statement = statement.where(
                InboxItemRecord.processing_status == processing_status
            )

        items = session.scalars(
            statement.order_by(InboxItemRecord.id.asc()).limit(limit)
        ).all()
        return [_item_to_dict(item) for item in items]


def update_item_in_db(item_id: int, raw_text: str) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.item_type != TEXT_ITEM_TYPE:
            return None

        item.raw_text = raw_text
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def delete_item_from_db(item_id: int) -> bool:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return False

        insight = session.get(ItemInsightRecord, item_id)
        if insight is not None:
            session.delete(insight)
        session.delete(item)
        session.commit()
        return True


def _item_to_note(item: dict) -> dict:
    return {
        "id": item["id"],
        "text": item["raw_text"],
        "created_at": item["created_at"],
    }


def add_note_to_db(text: str) -> dict:
    return _item_to_note(add_item_to_db(text))


def list_notes_from_db() -> list[dict]:
    return [
        _item_to_note(item)
        for item in list_items_from_db()
        if item["item_type"] == TEXT_ITEM_TYPE
    ]


def update_note_in_db(note_id: int, text: str) -> Optional[dict]:
    item = update_item_in_db(note_id, text)
    return _item_to_note(item) if item is not None else None


def delete_note_from_db(note_id: int) -> bool:
    return delete_item_from_db(note_id)


def start_analysis_run() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        run = AnalysisRunRecord(
            started_at=started_at,
            status=ANALYSIS_RUNNING,
            mode="pending",
        )
        session.add(run)
        session.commit()
        return run.id


def complete_analysis_run(run_id: int, result: dict) -> dict:
    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if run is None or run.status != ANALYSIS_RUNNING:
            raise ValueError("Analysis run is not available for completion")

        for bucket in result["buckets"]:
            for analyzed_item in bucket["notes"]:
                item_id = analyzed_item["id"]
                if session.get(InboxItemRecord, item_id) is None:
                    raise ValueError(
                        f"Analysis references missing item {item_id}"
                    )
                insight = session.get(ItemInsightRecord, item_id)
                if insight is None:
                    insight = ItemInsightRecord(item_id=item_id)
                    session.add(insight)
                insight.analysis_run_id = run_id
                insight.category = bucket["name"]
                insight.concise_title = analyzed_item["title"]
                insight.priority = analyzed_item["priority"]
                insight.updated_at = completed_at

        claimed_source_ids = set()
        for todo in result["todos"]:
            source_item_ids = [
                item_id
                for item_id in sorted(set(todo["source_note_ids"]))
                if item_id not in claimed_source_ids
            ]
            if not source_item_ids:
                continue
            claimed_source_ids.update(source_item_ids)

            for item_id in source_item_ids:
                if session.get(InboxItemRecord, item_id) is None:
                    raise ValueError(
                        f"Task references missing item {item_id}"
                    )

            existing_tasks = session.scalars(
                select(TaskRecord)
                .join(TaskSourceItemRecord)
                .where(TaskSourceItemRecord.item_id.in_(source_item_ids))
                .distinct()
                .order_by(TaskRecord.id.asc())
            ).all()

            if not existing_tasks:
                task = TaskRecord(
                    text=todo["task"],
                    priority=todo["priority"],
                    timing_text=todo["when"],
                    status=TASK_OPEN,
                    dedup_key=_task_dedup_key(source_item_ids),
                    created_at=completed_at,
                    updated_at=completed_at,
                )
                session.add(task)
                session.flush()
                for item_id in source_item_ids:
                    session.add(
                        TaskSourceItemRecord(
                            task_id=task.id,
                            item_id=item_id,
                        )
                    )
                continue

            for task in existing_tasks:
                task_source_ids = session.scalars(
                    select(TaskSourceItemRecord.item_id).where(
                        TaskSourceItemRecord.task_id == task.id
                    )
                ).all()
                changed = (
                    task.text != todo["task"]
                    or task.priority != todo["priority"]
                    or task.timing_text != todo["when"]
                )
                task.text = todo["task"]
                task.priority = todo["priority"]
                task.timing_text = todo["when"]
                task.dedup_key = _task_dedup_key(list(task_source_ids))
                if changed:
                    task.updated_at = completed_at

            if len(existing_tasks) == 1:
                task = existing_tasks[0]
                linked_source_ids = set(
                    session.scalars(
                        select(TaskSourceItemRecord.item_id).where(
                            TaskSourceItemRecord.task_id == task.id
                        )
                    ).all()
                )
                for item_id in source_item_ids:
                    if item_id not in linked_source_ids:
                        session.add(
                            TaskSourceItemRecord(
                                task_id=task.id,
                                item_id=item_id,
                            )
                        )
                        linked_source_ids.add(item_id)
                task.dedup_key = _task_dedup_key(
                    sorted(linked_source_ids)
                )

        run.completed_at = completed_at
        run.status = ANALYSIS_SUCCEEDED
        run.mode = result["mode"]
        run.result_json = json.dumps(result, ensure_ascii=False)
        session.commit()

    return {
        **result,
        "analysis_run_id": run_id,
        "generated_at": completed_at,
    }


def fail_analysis_run(run_id: int) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if run is None or run.status != ANALYSIS_RUNNING:
            return
        run.completed_at = completed_at
        run.status = ANALYSIS_FAILED
        run.mode = "error"
        run.result_json = None
        session.commit()


def get_latest_successful_analysis() -> Optional[dict]:
    with SessionLocal() as session:
        run = session.scalars(
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.status == ANALYSIS_SUCCEEDED)
            .order_by(
                AnalysisRunRecord.completed_at.desc(),
                AnalysisRunRecord.id.desc(),
            )
            .limit(1)
        ).first()
        if run is None:
            return None
        return {
            **json.loads(run.result_json),
            "analysis_run_id": run.id,
            "generated_at": run.completed_at,
        }


def _task_dedup_key(source_item_ids: list[int]) -> str:
    fingerprint = json.dumps(
        sorted(set(source_item_ids)),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _task_to_dict(session, task: TaskRecord) -> dict:
    source_item_ids = session.scalars(
        select(TaskSourceItemRecord.item_id)
        .where(TaskSourceItemRecord.task_id == task.id)
        .order_by(TaskSourceItemRecord.item_id.asc())
    ).all()
    return {
        "id": task.id,
        "text": task.text,
        "priority": task.priority,
        "timing_text": task.timing_text,
        "status": task.status,
        "source_item_ids": list(source_item_ids),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def list_tasks_from_db(status_filter: str = TASK_OPEN) -> list[dict]:
    if status_filter not in TASK_STATUSES | {"all"}:
        raise ValueError("Unsupported task status")

    with SessionLocal() as session:
        statement = select(TaskRecord).order_by(TaskRecord.id.asc())
        if status_filter != "all":
            statement = statement.where(TaskRecord.status == status_filter)
        tasks = session.scalars(statement).all()
        return [_task_to_dict(session, task) for task in tasks]


def set_task_status(task_id: int, task_status: str) -> Optional[dict]:
    if task_status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")

    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            return None
        if task.status != task_status:
            task.status = task_status
            task.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
        return _task_to_dict(session, task)


def batch_add_items_to_db(raw_texts: list[str]) -> list[dict]:
    """Insert multiple inbox items in a single atomic database transaction.

    Rolls back completely if any insertion fails.
    """
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        try:
            records = []
            for text in raw_texts:
                cleaned = text.strip()
                if cleaned:
                    item = InboxItemRecord(
                        item_type=TEXT_ITEM_TYPE,
                        raw_text=cleaned,
                        processing_status=READY_STATUS,
                        created_at=now,
                    )
                    session.add(item)
                    records.append(item)
            session.commit()
            return [_item_to_dict(item) for item in records]
        except Exception:
            session.rollback()
            raise


def backup_database_before_bulk() -> Optional[str]:
    """Create a backup of the SQLite database before bulk write operations.

    Retains the most recent 10 backups and silently skips in-memory or nonexistent files.
    """
    db_url = os.getenv("DATABASE_URL", DATABASE_URL)
    if not db_url.startswith("sqlite:///"):
        return None

    db_path_str = db_url.replace("sqlite:///", "")
    if not db_path_str or db_path_str == ":memory:":
        return None

    db_path = Path(db_path_str).resolve()
    if not db_path.exists() or not db_path.is_file():
        return None

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_backup_{timestamp}.db"

    try:
        shutil.copy2(db_path, backup_path)
    except OSError:
        return None

    # Rotate old backups: keep latest 10
    try:
        backups = sorted(
            backup_dir.glob(f"{db_path.stem}_backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[10:]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass

    return str(backup_path)


def record_ai_metric(
    operation: str,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: float = 0.0,
    estimated_cost_usd: float = 0.0,
    status: str = "success",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        rec = AIMetricRecord(
            operation=operation,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=round(estimated_cost_usd, 6),
            status=status,
            created_at=now,
        )
        session.add(rec)
        session.commit()
        return {
            "id": rec.id,
            "operation": rec.operation,
            "provider": rec.provider,
            "model": rec.model,
            "prompt_tokens": rec.prompt_tokens,
            "completion_tokens": rec.completion_tokens,
            "total_tokens": rec.total_tokens,
            "latency_ms": rec.latency_ms,
            "estimated_cost_usd": rec.estimated_cost_usd,
            "status": rec.status,
            "created_at": rec.created_at,
        }


def get_ai_metrics_summary() -> dict:
    with SessionLocal() as session:
        total_calls = session.scalar(select(func.count(AIMetricRecord.id))) or 0
        total_tokens = session.scalar(select(func.sum(AIMetricRecord.total_tokens))) or 0
        total_prompt_tokens = session.scalar(select(func.sum(AIMetricRecord.prompt_tokens))) or 0
        total_completion_tokens = session.scalar(select(func.sum(AIMetricRecord.completion_tokens))) or 0
        total_cost_usd = session.scalar(select(func.sum(AIMetricRecord.estimated_cost_usd))) or 0.0
        avg_latency_ms = session.scalar(select(func.avg(AIMetricRecord.latency_ms))) or 0.0

        recent_records = session.scalars(
            select(AIMetricRecord).order_by(AIMetricRecord.id.desc()).limit(10)
        ).all()

        recent_calls = [
            {
                "id": r.id,
                "operation": r.operation,
                "provider": r.provider,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "estimated_cost_usd": r.estimated_cost_usd,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in recent_records
        ]

        return {
            "total_calls": int(total_calls),
            "total_tokens": int(total_tokens),
            "total_prompt_tokens": int(total_prompt_tokens),
            "total_completion_tokens": int(total_completion_tokens),
            "total_cost_usd": round(float(total_cost_usd), 6),
            "avg_latency_ms": round(float(avg_latency_ms), 2),
            "recent_calls": recent_calls,
        }


def get_stale_items(days: int = 7) -> list[dict]:
    """Retrieve inbox items created more than `days` ago."""
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    with SessionLocal() as session:
        items = session.scalars(select(InboxItemRecord).order_by(InboxItemRecord.id.desc())).all()
        stale = []
        for it in items:
            try:
                # Handle varying ISO formats
                cleaned_ts = it.created_at.replace("Z", "+00:00")
                item_ts = datetime.fromisoformat(cleaned_ts).timestamp()
                if item_ts <= cutoff:
                    stale.append(_item_to_dict(it))
            except Exception:
                pass
        return stale



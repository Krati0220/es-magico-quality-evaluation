"""SQLAlchemy persistence layer: SQLite locally, PostgreSQL on Render (DATABASE_URL)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


def _database_url():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        db_dir = ROOT / "runs"
        db_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_dir / 'es_eval_studio.db'}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")
ENGINE = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(String(40), primary_key=True)
    name = Column(String(120), nullable=False)
    scope = Column(String(20), nullable=False)  # smoke | full
    baseline_version = Column(String(20), nullable=False, default="v1")
    candidate_version = Column(String(20), nullable=False, default="v2")
    status = Column(String(30), nullable=False, default="queued")  # queued | running | completed | partial | cancelled | failed
    stage = Column(String(20), nullable=False, default="all")
    use_mock = Column(Integer, nullable=False, default=0)
    completed_steps = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    manifest_json = Column(Text, nullable=False)
    review_doc_json = Column(Text, nullable=True)
    review_key_json = Column(Text, nullable=True)
    metrics_json = Column(Text, nullable=True)
    rows_json = Column(Text, nullable=True)
    report_md = Column(Text, nullable=True)


class EvalEvent(Base):
    __tablename__ = "eval_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), index=True, nullable=False)
    job_id = Column(String(40), index=True, nullable=False)
    stage = Column(String(20), nullable=False)
    attempt = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload_json = Column(Text, nullable=False)


def init_db():
    Base.metadata.create_all(bind=ENGINE)


def get_run_events(session, run_id):
    rows = session.execute(
        select(EvalEvent.payload_json).where(EvalEvent.run_id == run_id).order_by(EvalEvent.id.asc())
    ).scalars().all()
    return [json.loads(r) for r in rows]


def append_run_event(session, run_id, event):
    record = EvalEvent(
        run_id=run_id,
        job_id=event["job_id"],
        stage=event["stage"],
        attempt=int(event["attempt"]),
        status=event["status"],
        payload_json=json.dumps(event, ensure_ascii=False),
    )
    session.add(record)
    session.commit()


def db_backend_name():
    return "sqlite" if IS_SQLITE else "postgresql"

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from prisma.coordinator import PrismaCoordinator
from prisma.connectivity import monitor as connectivity

app = FastAPI(title="Prisma", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost", "http://localhost:1420"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}


# ── Request / response models ─────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    topic: str
    sources: Optional[list[str]] = None
    limit: Optional[int] = None
    zotero_only: bool = False


class JobStatus(BaseModel):
    job_id: str
    status: str            # pending | running | done | error
    papers_analyzed: int = 0
    authors_found: int = 0
    output_file: str = ""
    content_html: str = ""
    errors: list[str] = []


# ── Background worker ─────────────────────────────────────────────────────────

def _run_review(job_id: str, req: ReviewRequest) -> None:
    _jobs[job_id]["status"] = "running"
    try:
        from prisma.utils.config import ConfigLoader
        cfg = ConfigLoader()
        search_cfg = cfg.get_search_config()
        output_cfg = cfg.get_output_config()

        topic_safe = req.topic.replace(" ", "_").replace("/", "_")
        review_config = {
            "topic": req.topic,
            "sources": req.sources or search_cfg.sources,
            "limit": req.limit or search_cfg.default_limit,
            "output_file": f"{output_cfg.directory}/literature_review_{topic_safe}.md",
            "stream_name": None,
            "include_authors": False,
            "zotero_collections": None,
            "zotero_recent_years": None,
        }

        result = PrismaCoordinator().run_review(review_config)

        content_html = ""
        if result.success and result.output_file:
            try:
                from docu_craft.themes import ThemeManager
                from docu_craft.workflow import graph as workflow
                theme = ThemeManager.load("prisma")
                md = Path(result.output_file).read_text(encoding="utf-8")
                content_html = workflow.run(
                    md, from_fmt="md", to_fmt="html",
                    css=theme.css, style=theme.style,
                )
            except Exception:
                pass

        _jobs[job_id].update(
            status="done" if result.success else "error",
            papers_analyzed=result.papers_analyzed,
            authors_found=result.authors_found,
            output_file=result.output_file,
            content_html=content_html,
            errors=result.errors,
        )
    except Exception as exc:
        _jobs[job_id].update(status="error", errors=[str(exc)])


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "online": connectivity.is_online}


@app.get("/status")
def status():
    from prisma.utils.config import ConfigLoader
    try:
        cfg = ConfigLoader()
        config_ok = True
        config_error = None
    except Exception as exc:
        config_ok = False
        config_error = str(exc)

    return {
        "online": connectivity.is_online,
        "config": {"ok": config_ok, "error": config_error},
        "pending_jobs": sum(1 for j in _jobs.values() if j["status"] in ("pending", "running")),
    }


@app.post("/review", response_model=JobStatus, status_code=202)
def start_review(req: ReviewRequest):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "papers_analyzed": 0, "authors_found": 0,
                     "output_file": "", "content_html": "", "errors": []}
    _executor.submit(_run_review, job_id, req)
    return JobStatus(job_id=job_id, status="pending")


@app.get("/review/{job_id}", response_model=JobStatus)
def get_review(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatus(job_id=job_id, **job)

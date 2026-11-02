"""Run standard or AI Article Capture analysis without blocking preview startup."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from .errors import ArticleError
from .extractor import analyze_article_html
from .nlp_analysis import AnalysisCancelled, AiAnalysisError, OllamaClient, analyze_article_with_ai, ollama_client


@dataclass
class AnalysisJob:
    identifier: str
    mode: str
    page_html: str
    source_url: str
    title: str
    author: str
    created_at: float = field(default_factory=time.monotonic)
    status: str = "queued"
    progress: dict = field(default_factory=lambda: {"current": 0, "total": 0, "message": "Waiting to start analysis…"})
    result: dict | None = None
    error: str | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


class ArticleAnalysisJobs:
    """Own bounded, in-memory jobs and one-at-a-time model inference."""

    def __init__(self, client: OllamaClient = ollama_client):
        self._client = client
        self._lock = threading.RLock()
        self._jobs: dict[str, AnalysisJob] = {}
        self._ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="article-ai")
        self._standard_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="article-standard")

    def _prune(self) -> None:
        cutoff = time.monotonic() - 3600
        for identifier, job in list(self._jobs.items()):
            if job.status in {"completed", "failed", "cancelled"} and job.created_at < cutoff:
                del self._jobs[identifier]
        if len(self._jobs) >= 32:
            for identifier, job in list(self._jobs.items()):
                if job.status in {"completed", "failed", "cancelled"}:
                    del self._jobs[identifier]
                    if len(self._jobs) < 32:
                        break

    def submit(self, mode: str, page_html: str, source_url: str, title: str = "", author: str = "") -> dict:
        if mode not in {"standard", "ai"}:
            raise ValueError("Analysis mode must be 'standard' or 'ai'.")
        with self._lock:
            self._prune()
            if len(self._jobs) >= 32:
                raise RuntimeError("Too many article analyses are already in progress.")
            job = AnalysisJob(uuid.uuid4().hex, mode, page_html, source_url, title, author)
            self._jobs[job.identifier] = job
            executor = self._ai_executor if mode == "ai" else self._standard_executor
            job.future = executor.submit(self._run, job)
            return self._snapshot(job)

    def get(self, identifier: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(identifier)
            return self._snapshot(job) if job else None

    def cancel(self, identifier: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(identifier)
            if not job:
                return None
            if job.status not in {"completed", "failed", "cancelled"}:
                job.cancelled.set()
                job.status = "cancelled"
                job.page_html = ""
                job.progress = {**job.progress, "message": "Article analysis cancelled."}
                if job.future:
                    job.future.cancel()
            return self._snapshot(job)

    @staticmethod
    def _snapshot(job: AnalysisJob) -> dict:
        return {
            "jobId": job.identifier,
            "mode": job.mode,
            "status": job.status,
            "progress": dict(job.progress),
            "result": job.result,
            "error": job.error,
        }

    def _update_progress(self, job: AnalysisJob, current: int, total: int, message: str) -> None:
        with self._lock:
            if job.status == "cancelled":
                return
            job.status = "running"
            job.progress = {"current": current, "total": total, "message": message}

    def _finish(self, job: AnalysisJob, result: dict) -> None:
        with self._lock:
            if job.status == "cancelled":
                return
            job.result = result
            job.status = "completed"
            job.progress = {"current": 1, "total": 1, "message": "Article analysis complete."}
            # Once finished, retain only the analyzed result needed by the preview.
            job.page_html = ""
            job.source_url = job.title = job.author = ""

    def _fail(self, job: AnalysisJob, message: str) -> None:
        with self._lock:
            if job.status == "cancelled":
                return
            job.status = "failed"
            job.error = message
            job.progress = {**job.progress, "message": message}
            job.page_html = ""
            job.source_url = job.title = job.author = ""

    def _run(self, job: AnalysisJob) -> None:
        if job.cancelled.is_set():
            return
        with self._lock:
            if job.status != "cancelled":
                job.status = "running"
        started = time.perf_counter()
        try:
            if job.mode == "ai":
                try:
                    result = analyze_article_with_ai(
                        job.page_html,
                        job.source_url,
                        self._client,
                        title=job.title,
                        author=job.author,
                        progress=lambda current, total, message: self._update_progress(job, current, total, message),
                        cancelled=job.cancelled,
                    )
                except AnalysisCancelled:
                    with self._lock:
                        job.cancelled.set()
                        job.status = "cancelled"
                        job.page_html = ""
                    return
                except Exception as failure:
                    if job.cancelled.is_set():
                        return
                    reason = str(failure) if isinstance(failure, AiAnalysisError) else "The AI analysis service failed unexpectedly."
                    result = analyze_article_html(job.page_html, job.source_url, title=job.title, author=job.author)
                    result["warnings"] = [*result.get("warnings", []), f"AI analysis unavailable; standard extraction was used. {reason}"]
                    result["analysisMode"] = "standard"
                    result["fallbackReason"] = reason
            else:
                result = analyze_article_html(job.page_html, job.source_url, title=job.title, author=job.author)
                result["analysisMode"] = "standard"
                result["fallbackReason"] = None
            if job.cancelled.is_set():
                return
            result["analysisTimeMs"] = round((time.perf_counter() - started) * 1000)
            self._finish(job, result)
        except ArticleError as failure:
            self._fail(job, str(failure))
        except Exception:
            self._fail(job, "Article analysis failed. Use standard extraction or try again.")

    def close(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    job.cancelled.set()
                    job.status = "cancelled"
                    job.progress = {**job.progress, "message": "Article analysis cancelled."}
                    job.page_html = ""
                    job.source_url = job.title = job.author = ""
        self._ai_executor.shutdown(wait=False, cancel_futures=True)
        self._standard_executor.shutdown(wait=False, cancel_futures=True)
        self._client.close()


analysis_jobs = ArticleAnalysisJobs()

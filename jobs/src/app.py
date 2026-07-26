"""
FastAPI application for the Celery PDF processing service.
Provides health and task-status endpoints for the Server service.
"""

import logging
from typing import Any

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.celery_app import celery_app

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF Processing Service",
    description="Celery-based service for processing PDF files",
    version="1.0.0",
)


class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    error: str | None = None
    progress_message: str | None = None


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "pdf-processing"}


@app.get("/task/{task_id}/status", response_model=TaskStatus)
async def get_task_status(task_id: str) -> TaskStatus:
    """
    Get the status of a processing task by ID.
    """
    try:
        # Get task result from Celery
        task_result: AsyncResult[dict[str, Any]] = AsyncResult(
            task_id,
            app=celery_app,
        )

        if task_result.state == "PENDING":
            # Task is waiting or doesn't exist
            status_response = TaskStatus(
                task_id=task_id,
                status="pending",
                meta={"message": "Task is pending or does not exist"},
            )
        elif task_result.state == "PROGRESS":
            # Task is in progress - extract progress details
            progress_info = task_result.info or {}
            status_response = TaskStatus(
                task_id=task_id,
                status="running",
                meta=progress_info,
                progress_message=progress_info.get("status", "Processing..."),
            )
        elif task_result.state == "SUCCESS":
            # Task completed successfully
            result = task_result.result
            if not isinstance(result, dict):
                raise TypeError("Celery task returned a non-object result")
            status_response = TaskStatus(
                task_id=task_id,
                status="completed",
                result=result,
                meta={"completed_at": str(task_result.date_done)},
            )
        elif task_result.state == "FAILURE":
            # Task failed
            status_response = TaskStatus(
                task_id=task_id,
                status="failed",
                error="task_failed",
                meta={"failed_at": str(task_result.date_done)},
            )
        else:
            # Unknown state
            status_response = TaskStatus(
                task_id=task_id,
                status=task_result.state.lower(),
                meta={"message": "Task is in an unexpected state"},
            )

        return status_response

    except Exception as exc:
        logger.error(
            "Failed to read task status for %s (%s)",
            task_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="task_status_failed") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

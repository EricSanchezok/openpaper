"""Health endpoint for the Scholens background worker deployment."""

from fastapi import FastAPI
from src.observability import configure_jobs_observability, instrument_jobs_api

configure_jobs_observability()

app = FastAPI(
    title="Scholens Jobs",
    description="Health endpoint for durable Scholens background workers",
    version="1.0.0",
)
instrument_jobs_api(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "scholens-jobs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=7302)

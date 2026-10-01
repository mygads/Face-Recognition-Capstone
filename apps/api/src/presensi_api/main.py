from fastapi import FastAPI

app = FastAPI(title="Presensi Core API", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Expose process health for local development and service checks."""
    return {"status": "ok"}

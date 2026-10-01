from fastapi import FastAPI

app = FastAPI(title="Presensi Central AI Service", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Expose process health; recognition endpoints belong to a later task."""
    return {"status": "ok"}

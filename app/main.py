from fastapi import FastAPI

app = FastAPI(title="T1 Monolith")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    """Indica que a aplicação está disponível."""
    return {"status": "ok"}

from fastapi import FastAPI

from backend.app.api.errors import install_error_handlers
from backend.app.api.v1.repositories import router as repositories_router

app = FastAPI(title="RepoAtlas API")
install_error_handlers(app)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app.include_router(repositories_router, prefix="/api/v1")

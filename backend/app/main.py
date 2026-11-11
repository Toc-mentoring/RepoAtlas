from fastapi import FastAPI

from backend.app.api.errors import install_error_handlers
from backend.app.api.v1.analyses import analyses_router, repository_analyses_router
from backend.app.api.v1.diagrams import analysis_diagrams_router, diagrams_router
from backend.app.api.v1.repositories import router as repositories_router
from backend.app.api.v1.results import router as results_router

app = FastAPI(title="RepoAtlas API")
install_error_handlers(app)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app.include_router(repositories_router, prefix="/api/v1")
app.include_router(repository_analyses_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(results_router, prefix="/api/v1")
app.include_router(analysis_diagrams_router, prefix="/api/v1")
app.include_router(diagrams_router, prefix="/api/v1")

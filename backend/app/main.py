import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api import deps
from backend.app.api.errors import install_error_handlers
from backend.app.api.v1.analyses import analyses_router, repository_analyses_router
from backend.app.api.v1.diagrams import analysis_diagrams_router, diagrams_router
from backend.app.api.v1.repositories import router as repositories_router
from backend.app.api.v1.results import router as results_router

logger = logging.getLogger(__name__)

app = FastAPI(title="RepoAtlas API")
install_error_handlers(app)


@app.get("/healthz")
def healthz():
    # DB에 실제로 질의가 되는지까지 확인한다. 실패하면 503 (API_SPEC H01).
    try:
        with deps.get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        logger.warning("health check failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}


app.include_router(repositories_router, prefix="/api/v1")
app.include_router(repository_analyses_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(results_router, prefix="/api/v1")
app.include_router(analysis_diagrams_router, prefix="/api/v1")
app.include_router(diagrams_router, prefix="/api/v1")

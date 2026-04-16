from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run
from config import settings
from database import connect_db, disconnect_db
from routers.auth import router as auth_router
from routers.github_app import router as github_app_router
from routers.workspaces import router as workspace_router
from services.pipeline_runtime import pipeline_runtime
from services.state_reset import clear_backend_state, clear_runtime_state

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.RESET_CI_CD_STATE_ON_STARTUP:
        await clear_backend_state()
        clear_runtime_state()
    await connect_db()
    clear_runtime_state()
    await pipeline_runtime.start()
    yield
    await pipeline_runtime.stop()
    await disconnect_db()


app = FastAPI(
    title="PipelineIQ API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(github_app_router)


@app.get("/")
def read_root():
    return {"message": "PipelineIQ API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=8000)

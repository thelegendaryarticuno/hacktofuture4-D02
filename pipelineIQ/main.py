from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run
from config import settings
from database import connect_db, disconnect_db
from routers.auth import router as auth_router
from routers.github_app import router as github_app_router
from routers.workspaces import router as workspace_router

# ── Lifespan: DB connect / disconnect ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await disconnect_db()


# ── Application ───────────────────────────────────────────────────
app = FastAPI(
    title="PipelineIQ API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────
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

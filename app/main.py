from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import FRONTEND_STATIC_DIR
from app.database import Database
from app.models import SkillArchiveMetadata, SkillDetail, SkillListItem, SkillUploadResponse
from app.repository import SkillRepository


database = Database()
repository = SkillRepository(database)
_STATIC_DIR = FRONTEND_STATIC_DIR
_INDEX_FILE = _STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(
    title="Skills Hub API",
    version="0.1.0",
    description="MVP API for uploading, browsing, previewing, and downloading skills.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills", response_model=list[SkillListItem])
def list_skills() -> list[SkillListItem]:
    return repository.list_skills()


@app.get("/api/skills/search", response_model=list[SkillListItem])
def search_skills(q: str = Query(min_length=1, max_length=80)) -> list[SkillListItem]:
    return repository.list_skills(q)


@app.get("/api/skills/{slug}", response_model=SkillDetail)
def get_skill_detail(slug: str) -> SkillDetail:
    return repository.get_skill_detail(slug)


@app.post("/api/skills", response_model=SkillUploadResponse, status_code=201)
async def create_skill(file: UploadFile = File(...)) -> SkillUploadResponse:
    return await repository.create_skill_from_zip(file)


@app.post("/api/skills/inspect", response_model=SkillUploadResponse)
async def inspect_skill(file: UploadFile = File(...)) -> SkillUploadResponse:
    return await repository.inspect_skill_archive(file)


@app.get("/api/skills/{slug}/archive", response_model=SkillArchiveMetadata)
def get_archive_metadata(slug: str) -> SkillArchiveMetadata:
    return repository.get_archive_metadata(slug)


@app.get("/api/skills/{slug}/download")
def download_skill_archive(slug: str) -> FileResponse:
    archive_path, archive_filename = repository.record_download_and_get_path(slug)
    return FileResponse(archive_path, filename=archive_filename, media_type="application/zip")


@app.get("/")
def home_page() -> FileResponse:
    if _INDEX_FILE.exists():
        return FileResponse(_INDEX_FILE)
    raise HTTPException(status_code=404, detail="Frontend static files not found")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    candidate = (_STATIC_DIR / full_path).resolve()
    static_root = _STATIC_DIR.resolve()
    if candidate.exists() and candidate.is_file() and static_root in candidate.parents:
        return FileResponse(candidate)

    if _INDEX_FILE.exists():
        return FileResponse(_INDEX_FILE)

    raise HTTPException(status_code=404, detail="Frontend static files not found")

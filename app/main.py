from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.auth_service import AuthService
from app.config import FRONTEND_STATIC_DIR
from app.database import Database
from app.feishu_auth_service import FeishuAuthService
from app.feishu_settings_service import FeishuSettingsService
from app.models import (
    AuthResponse,
    AuthUser,
    BootstrapRequest,
    BootstrapStatusResponse,
    CreateUserRequest,
    FeishuAuthorizeUrlResponse,
    FeishuLoginRequest,
    FeishuSettingsUpdateRequest,
    FeishuSettingsView,
    FeishuStatusResponse,
    LoginRequest,
    MessageResponse,
    SkillArchiveMetadata,
    SkillDetail,
    SkillListItem,
    SkillUploadResponse,
    UserListResponse,
)
from app.repository import SkillRepository


database = Database()
repository = SkillRepository(database)
auth_service = AuthService(database)
feishu_settings_service = FeishuSettingsService(database)
feishu_auth_service = FeishuAuthService()
_STATIC_DIR = FRONTEND_STATIC_DIR
_INDEX_FILE = _STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(
    title="Skill Hub API",
    version="0.2.0",
    description="Skills Store API for browsing, publishing, and account management.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    return auth_service.get_user_by_token(token)


def get_admin_user(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    auth_service.assert_admin(current_user)
    return current_user


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status() -> BootstrapStatusResponse:
    return BootstrapStatusResponse(requires_setup=auth_service.requires_bootstrap())


@app.post("/api/auth/bootstrap", response_model=AuthResponse)
def bootstrap_admin(body: BootstrapRequest) -> AuthResponse:
    session = auth_service.bootstrap_admin(body.username, body.password)
    return AuthResponse(token=session.token, user=session.user)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest) -> AuthResponse:
    session = auth_service.login(body.username, body.password)
    return AuthResponse(token=session.token, user=session.user)


@app.post("/api/auth/logout", response_model=MessageResponse)
def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
    current_user: AuthUser = Depends(get_current_user),
) -> MessageResponse:
    del current_user
    if authorization and authorization.startswith("Bearer "):
        auth_service.revoke_token(authorization.removeprefix("Bearer ").strip())
    return MessageResponse(message="已退出登录")


@app.get("/api/auth/me", response_model=AuthUser)
def me(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return current_user


@app.get("/api/auth/feishu/status", response_model=FeishuStatusResponse)
def feishu_status() -> FeishuStatusResponse:
    return feishu_settings_service.get_public_status()


@app.get(
    "/api/auth/feishu/authorize-url",
    response_model=FeishuAuthorizeUrlResponse,
)
def feishu_authorize_url(
    redirect_uri: str | None = Query(default=None),
) -> FeishuAuthorizeUrlResponse:
    return FeishuAuthorizeUrlResponse(
        authorize_url=feishu_settings_service.build_authorize_url(redirect_uri)
    )


@app.post("/api/auth/feishu/login", response_model=AuthResponse)
def feishu_login(body: FeishuLoginRequest) -> AuthResponse:
    config = feishu_settings_service.assert_login_enabled()
    user_access_token = feishu_auth_service.exchange_code(
        base_url=config.base_url,
        app_id=config.app_id or "",
        app_secret=config.app_secret or "",
        code=body.code,
    )
    user_info = feishu_auth_service.get_user_info(
        base_url=config.base_url,
        user_access_token=user_access_token,
    )
    session = auth_service.login_by_feishu(
        union_id=user_info.union_id,
        open_id=user_info.open_id,
        name=user_info.name,
        avatar_url=user_info.avatar_url,
    )
    return AuthResponse(token=session.token, user=session.user)


@app.get("/api/admin/feishu-settings", response_model=FeishuSettingsView)
def get_feishu_settings(
    _: AuthUser = Depends(get_admin_user),
) -> FeishuSettingsView:
    return feishu_settings_service.get_settings_view()


@app.put("/api/admin/feishu-settings", response_model=FeishuSettingsView)
def update_feishu_settings(
    body: FeishuSettingsUpdateRequest,
    _: AuthUser = Depends(get_admin_user),
) -> FeishuSettingsView:
    return feishu_settings_service.update_settings(
        enabled=body.enabled,
        app_id=body.app_id,
        app_secret=body.app_secret,
        base_url=body.base_url,
    )


@app.get("/api/admin/users", response_model=UserListResponse)
def list_users(_: AuthUser = Depends(get_admin_user)) -> UserListResponse:
    return UserListResponse(items=auth_service.list_users())


@app.post("/api/admin/users", response_model=AuthUser, status_code=201)
def create_user(
    body: CreateUserRequest,
    _: AuthUser = Depends(get_admin_user),
) -> AuthUser:
    return auth_service.create_user(
        username=body.username,
        password=body.password,
        display_name=body.display_name,
    )


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
async def create_skill(
    file: UploadFile = File(...),
    current_user: AuthUser = Depends(get_current_user),
) -> SkillUploadResponse:
    return await repository.create_skill_from_zip(file, current_user)


@app.post("/api/skills/inspect", response_model=SkillUploadResponse)
async def inspect_skill(
    file: UploadFile = File(...),
    _: AuthUser = Depends(get_current_user),
) -> SkillUploadResponse:
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

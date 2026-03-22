from datetime import datetime

from pydantic import BaseModel, Field


class SkillPreviewFile(BaseModel):
    path: str
    content: str


class SkillListItem(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    archive_filename: str
    downloads: int
    created_at: datetime
    preview_paths: list[str] = Field(default_factory=list)
    publisher_name: str | None = None


class SkillDetail(SkillListItem):
    preview_files: list[SkillPreviewFile] = Field(default_factory=list)
    updated_at: datetime


class SkillUploadResponse(BaseModel):
    slug: str
    name: str
    description: str
    preview_paths: list[str] = Field(default_factory=list)


class SkillArchiveMetadata(BaseModel):
    skill_slug: str
    archive_filename: str
    download_url: str


class AuthUser(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime
    display_name: str | None = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class UserListResponse(BaseModel):
    items: list[AuthUser] = Field(default_factory=list)


class BootstrapStatusResponse(BaseModel):
    requires_setup: bool


class BootstrapRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class FeishuLoginRequest(BaseModel):
    code: str
    redirect_uri: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: AuthUser


class FeishuStatusResponse(BaseModel):
    enabled: bool
    app_id: str | None = None


class FeishuAuthorizeUrlResponse(BaseModel):
    authorize_url: str


class FeishuSettingsView(BaseModel):
    enabled: bool
    app_id: str | None = None
    has_app_secret: bool
    base_url: str


class FeishuSettingsUpdateRequest(BaseModel):
    enabled: bool
    app_id: str | None = None
    app_secret: str | None = None
    base_url: str = "https://open.feishu.cn"


class MessageResponse(BaseModel):
    message: str

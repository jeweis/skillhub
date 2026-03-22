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
    published_by_user_id: int | None = None
    tags: list[str] = Field(default_factory=list)


class SkillDetail(SkillListItem):
    preview_files: list[SkillPreviewFile] = Field(default_factory=list)
    updated_at: datetime


class SkillUploadResponse(BaseModel):
    slug: str
    name: str
    description: str
    preview_paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SkillConflictDetail(BaseModel):
    code: str
    message: str
    slug: str
    can_overwrite: bool = False


class SkillArchiveMetadata(BaseModel):
    skill_slug: str
    archive_filename: str
    download_url: str


class SkillTagOption(BaseModel):
    label: str
    admin_only: bool = False


class SkillTagListResponse(BaseModel):
    items: list[SkillTagOption] = Field(default_factory=list)


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


class SearchSettingsView(BaseModel):
    enabled: bool
    provider: str
    base_url: str
    model: str | None = None
    has_bearer_token: bool = False
    configured: bool = False


class SearchSettingsUpdateRequest(BaseModel):
    enabled: bool
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str | None = None
    bearer_token: str | None = None


class MessageResponse(BaseModel):
    message: str

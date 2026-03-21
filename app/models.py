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

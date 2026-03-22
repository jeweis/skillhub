import io
import json
import re
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import ARCHIVES_DIR
from app.models import (
    AuthUser,
    SkillConflictDetail,
    SkillArchiveMetadata,
    SkillDetail,
    SkillListItem,
    SkillPreviewFile,
    SkillTagListResponse,
    SkillTagOption,
    SkillUploadResponse,
)

PREVIEW_BASENAMES = ("SKILL.md", "README.md", "REFERENCE.md")
TAG_RECOMMENDED = "推荐"
TAG_HOT = "热门"
TAG_RESEARCH = "研发"
TAG_OTHER = "其他"
ALLOWED_TAGS = (TAG_RECOMMENDED, TAG_HOT, TAG_RESEARCH, TAG_OTHER)
ADMIN_ONLY_TAGS = {TAG_RECOMMENDED}
MAX_TAG_COUNT = 8
MAX_TAG_LENGTH = 12


class SkillRepository:
    def __init__(self, database):
        self.database = database

    def list_skills(self, query: str | None = None) -> list[SkillListItem]:
        rows = self._fetch_skill_rows(query=query)
        return self._rows_to_skill_items(rows)

    def list_skills_by_ids(self, skill_ids: list[int]) -> list[SkillListItem]:
        if not skill_ids:
            return []
        rows = self._fetch_skill_rows(skill_ids=skill_ids)
        items = self._rows_to_skill_items(rows)
        order_map = {skill_id: index for index, skill_id in enumerate(skill_ids)}
        items.sort(key=lambda item: order_map.get(item.id, len(order_map)))
        return items

    def _fetch_skill_rows(
        self,
        *,
        query: str | None = None,
        skill_ids: list[int] | None = None,
    ):
        sql = """
            SELECT
                s.id,
                s.slug,
                s.name,
                s.description,
                s.archive_filename,
                s.downloads,
                s.created_at,
                s.publisher_name,
                s.published_by_user_id,
                GROUP_CONCAT(DISTINCT spf.path) AS preview_paths,
                GROUP_CONCAT(DISTINCT st.tag) AS tags
            FROM skills s
            LEFT JOIN skill_preview_files spf ON spf.skill_id = s.id
            LEFT JOIN skill_tags st ON st.skill_id = s.id
            WHERE 1 = 1
        """
        params: list[object] = []
        if skill_ids:
            placeholders = ",".join("?" for _ in skill_ids)
            sql += f" AND s.id IN ({placeholders})"
            params.extend(skill_ids)
        if query:
            needle = f"%{query.strip()}%"
            sql += """
                AND (
                    s.name LIKE ?
                    OR s.slug LIKE ?
                    OR s.description LIKE ?
                    OR COALESCE(s.publisher_name, '') LIKE ?
                    OR COALESCE(st.tag, '') LIKE ?
                )
            """
            params.extend([needle, needle, needle, needle, needle])
        sql += " GROUP BY s.id ORDER BY s.created_at DESC"
        with self.database.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _rows_to_skill_items(self, rows) -> list[SkillListItem]:
        return [
            SkillListItem.model_validate(
                {
                    **dict(row),
                    "preview_paths": self._split_values(row["preview_paths"]),
                    "tags": self._sort_tags(self._split_values(row["tags"])),
                }
            )
            for row in rows
        ]

    def list_search_documents(self) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            skill_rows = conn.execute(
                """
                SELECT id, name, description
                FROM skills
                ORDER BY id
                """
            ).fetchall()
            preview_rows = conn.execute(
                """
                SELECT skill_id, path, content
                FROM skill_preview_files
                ORDER BY skill_id, path
                """
            ).fetchall()
            tag_rows = conn.execute(
                """
                SELECT skill_id, tag
                FROM skill_tags
                ORDER BY skill_id, tag
                """
            ).fetchall()

        previews_by_skill: dict[int, list[str]] = {}
        for row in preview_rows:
            previews_by_skill.setdefault(int(row["skill_id"]), []).append(
                f'{row["path"]}\n{row["content"]}'
            )

        tags_by_skill: dict[int, list[str]] = {}
        for row in tag_rows:
            tags_by_skill.setdefault(int(row["skill_id"]), []).append(str(row["tag"]))

        return [
            {
                "skill_id": int(row["id"]),
                "content": self._build_search_document(
                    name=str(row["name"]),
                    description=str(row["description"]),
                    previews=previews_by_skill.get(int(row["id"]), []),
                    tags=tags_by_skill.get(int(row["id"]), []),
                ),
            }
            for row in skill_rows
        ]

    def get_search_document_by_slug(self, slug: str) -> dict[str, object] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, description
                FROM skills
                WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
            if row is None:
                return None
            preview_rows = conn.execute(
                """
                SELECT path, content
                FROM skill_preview_files
                WHERE skill_id = ?
                ORDER BY path
                """,
                (row["id"],),
            ).fetchall()
            tag_rows = conn.execute(
                """
                SELECT tag
                FROM skill_tags
                WHERE skill_id = ?
                ORDER BY tag
                """,
                (row["id"],),
            ).fetchall()

        previews = [f'{item["path"]}\n{item["content"]}' for item in preview_rows]
        tags = [str(item["tag"]) for item in tag_rows]
        return {
            "skill_id": int(row["id"]),
            "content": self._build_search_document(
                name=str(row["name"]),
                description=str(row["description"]),
                previews=previews,
                tags=tags,
            ),
        }

    @staticmethod
    def _build_search_document(
        *,
        name: str,
        description: str,
        previews: list[str],
        tags: list[str],
    ) -> str:
        parts = [name.strip(), description.strip()]
        if tags:
            parts.append("标签: " + " ".join(tag.strip() for tag in tags if tag.strip()))
        parts.extend(item.strip() for item in previews if item.strip())
        return "\n\n".join(part for part in parts if part)

    def get_skill_detail(self, slug: str) -> SkillDetail:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    slug,
                    name,
                    description,
                    archive_filename,
                    downloads,
                    created_at,
                    updated_at,
                    publisher_name,
                    published_by_user_id
                FROM skills
                WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
            preview_rows = conn.execute(
                """
                SELECT path, content
                FROM skill_preview_files
                WHERE skill_id = ?
                ORDER BY
                    CASE path
                        WHEN 'SKILL.md' THEN 1
                        WHEN 'README.md' THEN 2
                        WHEN 'REFERENCE.md' THEN 3
                        ELSE 9
                    END,
                    path
                """,
                (row["id"],),
            ).fetchall()
            tag_rows = conn.execute(
                "SELECT tag FROM skill_tags WHERE skill_id = ?",
                (row["id"],),
            ).fetchall()

        preview_files = [
            SkillPreviewFile.model_validate(dict(item)) for item in preview_rows
        ]
        tags = self._sort_tags([str(item["tag"]) for item in tag_rows])
        return SkillDetail.model_validate(
            {
                **dict(row),
                "preview_paths": [item.path for item in preview_files],
                "preview_files": preview_files,
                "tags": tags,
            }
        )

    def get_archive_metadata(self, slug: str) -> SkillArchiveMetadata:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT slug, archive_filename FROM skills WHERE slug = ?",
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
        return SkillArchiveMetadata(
            skill_slug=row["slug"],
            archive_filename=row["archive_filename"],
            download_url=f"/api/skills/{row['slug']}/download",
        )

    def list_tag_options(self) -> SkillTagListResponse:
        return SkillTagListResponse(
            items=[
                SkillTagOption(label=TAG_RECOMMENDED, admin_only=True),
                SkillTagOption(label=TAG_HOT),
                SkillTagOption(label=TAG_RESEARCH),
                SkillTagOption(label=TAG_OTHER),
            ]
        )

    async def inspect_skill_archive(self, upload: UploadFile) -> SkillUploadResponse:
        archive_bytes, _ = await self._read_archive(upload)
        parsed = self._parse_skill_archive(archive_bytes)
        return SkillUploadResponse(
            slug=self._slugify(parsed["name"]),
            name=parsed["name"],
            description=parsed["description"],
            preview_paths=[item["path"] for item in parsed["preview_files"]],
            tags=[],
        )

    async def create_skill_from_zip(
        self,
        upload: UploadFile,
        current_user: AuthUser,
        tags: list[str] | None = None,
        overwrite: bool = False,
    ) -> SkillUploadResponse:
        archive_bytes, filename = await self._read_archive(upload)
        parsed = self._parse_skill_archive(archive_bytes)
        slug = self._slugify(parsed["name"])
        normalized_tags = self._normalize_tags(tags or [], current_user=current_user)
        existing_skill = self._find_existing_skill(parsed["name"], slug)
        if existing_skill is not None:
            self._assert_replaceable_skill(
                existing_skill=existing_skill,
                current_user=current_user,
                overwrite=overwrite,
            )
        archive_path = self._write_archive(slug, archive_bytes)

        try:
            with self.database.connect() as conn:
                if existing_skill is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO skills (
                            slug,
                            name,
                            description,
                            archive_filename,
                            archive_path,
                            published_by_user_id,
                            publisher_name,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            slug,
                            parsed["name"],
                            parsed["description"],
                            Path(filename).name,
                            str(archive_path),
                            current_user.id,
                            current_user.display_name or current_user.username,
                        ),
                    )
                    skill_id = int(cursor.lastrowid)
                else:
                    skill_id = int(existing_skill["id"])
                    conn.execute(
                        """
                        UPDATE skills
                        SET
                            name = ?,
                            description = ?,
                            archive_filename = ?,
                            archive_path = ?,
                            publisher_name = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            parsed["name"],
                            parsed["description"],
                            Path(filename).name,
                            str(archive_path),
                            current_user.display_name or current_user.username,
                            skill_id,
                        ),
                    )
                    conn.execute(
                        "DELETE FROM skill_preview_files WHERE skill_id = ?",
                        (skill_id,),
                    )
                    conn.execute(
                        "DELETE FROM skill_tags WHERE skill_id = ?",
                        (skill_id,),
                    )
                for preview_file in parsed["preview_files"]:
                    conn.execute(
                        """
                        INSERT INTO skill_preview_files (skill_id, path, content)
                        VALUES (?, ?, ?)
                        """,
                        (skill_id, preview_file["path"], preview_file["content"]),
                    )
                self._replace_skill_tags(conn, skill_id=skill_id, tags=normalized_tags)
        except Exception:
            if existing_skill is None:
                archive_path.unlink(missing_ok=True)
            raise

        return SkillUploadResponse(
            slug=slug,
            name=parsed["name"],
            description=parsed["description"],
            preview_paths=[item["path"] for item in parsed["preview_files"]],
            tags=normalized_tags,
        )

    def delete_skill(self, slug: str, current_user: AuthUser) -> None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, archive_path, published_by_user_id
                FROM skills
                WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
            owner_id = row["published_by_user_id"]
            if current_user.role != "admin" and owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="你没有权限删除这个 Skill")
            conn.execute("DELETE FROM skills WHERE id = ?", (row["id"],))
        Path(str(row["archive_path"])).unlink(missing_ok=True)

    def add_recommended_tag(self, slug: str, current_user: AuthUser) -> SkillDetail:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以添加推荐标签")
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT id FROM skills WHERE slug = ?",
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
            conn.execute(
                """
                INSERT INTO skill_tags (skill_id, tag)
                VALUES (?, ?)
                ON CONFLICT(skill_id, tag) DO NOTHING
                """,
                (row["id"], TAG_RECOMMENDED),
            )
        return self.get_skill_detail(slug)

    def record_download_and_get_path(self, slug: str) -> tuple[Path, str]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT archive_path, archive_filename
                FROM skills
                WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
            conn.execute(
                """
                UPDATE skills
                SET downloads = downloads + 1, updated_at = CURRENT_TIMESTAMP
                WHERE slug = ?
                """,
                (slug,),
            )
        archive_path = Path(row["archive_path"])
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="Archive file not found")
        return archive_path, row["archive_filename"]

    @staticmethod
    def parse_tags_form(tags_json: str | None) -> list[str]:
        raw = (tags_json or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="标签参数格式不正确") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="标签参数格式不正确")
        return [str(item).strip() for item in parsed if str(item).strip()]

    async def _read_archive(self, upload: UploadFile) -> tuple[bytes, str]:
        filename = upload.filename or "skill.zip"
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip uploads are supported")
        archive_bytes = await upload.read()
        if not archive_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return archive_bytes, filename

    def _parse_skill_archive(self, archive_bytes: bytes) -> dict[str, object]:
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                entries = self._collect_preview_files(archive)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid zip file") from exc

        skill_md = entries.get("SKILL.md")
        if skill_md is None:
            raise HTTPException(
                status_code=400,
                detail="SKILL.md is required in the zip archive",
            )

        name, description = self._extract_name_and_description(skill_md)
        preview_files = [{"path": key, "content": value} for key, value in entries.items()]
        return {
            "name": name,
            "description": description,
            "preview_files": preview_files,
        }

    def _collect_preview_files(self, archive: zipfile.ZipFile) -> dict[str, str]:
        found: dict[str, str] = {}
        for member_name in archive.namelist():
            if member_name.endswith("/"):
                continue
            basename = Path(member_name).name
            if basename not in PREVIEW_BASENAMES or basename in found:
                continue
            with archive.open(member_name) as file_handle:
                content = file_handle.read().decode("utf-8", errors="ignore").strip()
            found[basename] = content
        return found

    def _extract_name_and_description(self, skill_md: str) -> tuple[str, str]:
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
            skill_md,
            re.DOTALL,
        )
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            body = frontmatter_match.group(2)
            name = self._extract_frontmatter_value(frontmatter, "name")
            description = self._extract_frontmatter_value(frontmatter, "description")
            if name and description:
                return name, description
            extracted_name = name or self._extract_heading(body)
            extracted_description = description or self._extract_first_paragraph(body)
            return extracted_name, extracted_description
        return self._extract_heading(skill_md), self._extract_first_paragraph(skill_md)

    @staticmethod
    def _extract_frontmatter_value(frontmatter: str, key: str) -> str | None:
        match = re.search(rf"^{key}:\s*(.+)$", frontmatter, re.MULTILINE)
        if match is None:
            return None
        return match.group(1).strip().strip('"').strip("'")

    @staticmethod
    def _extract_heading(markdown: str) -> str:
        match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Untitled Skill"

    @staticmethod
    def _extract_first_paragraph(markdown: str) -> str:
        cleaned = re.sub(
            r"^---\s*\n.*?\n---\s*\n?",
            "",
            markdown,
            flags=re.DOTALL,
        ).strip()
        cleaned = re.sub(
            r"^#\s+.+$",
            "",
            cleaned,
            count=1,
            flags=re.MULTILINE,
        ).strip()
        parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        return parts[0] if parts else "No description provided."

    @staticmethod
    def _slugify(value: str) -> str:
        lowered = value.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return slug or "untitled-skill"

    def _find_existing_skill(self, name: str, slug: str):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, slug, name, published_by_user_id
                FROM skills
                WHERE LOWER(name) = LOWER(?) OR slug = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (name.strip(), slug),
            ).fetchone()

    def _assert_replaceable_skill(
        self,
        *,
        existing_skill,
        current_user: AuthUser,
        overwrite: bool,
    ) -> None:
        existing_slug = str(existing_skill["slug"])
        owner_id = existing_skill["published_by_user_id"]
        is_owner = owner_id == current_user.id

        if not is_owner:
            raise HTTPException(status_code=409, detail="同名 Skill 已存在，不能重复上传")

        if overwrite:
            return

        raise HTTPException(
            status_code=409,
            detail=SkillConflictDetail(
                code="skill_exists_owned",
                message="你已上传过同名 Skill，可以选择覆盖现有内容",
                slug=existing_slug,
                can_overwrite=True,
            ).model_dump(),
        )

    def _normalize_tags(
        self,
        tags: list[str],
        *,
        current_user: AuthUser,
    ) -> list[str]:
        unique_tags: list[str] = []
        for tag in tags:
            normalized = tag.strip()
            if not normalized:
                continue
            if len(normalized) > MAX_TAG_LENGTH:
                raise HTTPException(status_code=400, detail="标签长度不能超过 12 个字符")
            if normalized in ADMIN_ONLY_TAGS and current_user.role != "admin":
                raise HTTPException(status_code=403, detail="推荐标签只能由管理员添加")
            if normalized not in unique_tags:
                unique_tags.append(normalized)
        if len(unique_tags) > MAX_TAG_COUNT:
            raise HTTPException(status_code=400, detail="标签数量不能超过 8 个")
        return self._sort_tags(unique_tags)

    @staticmethod
    def _replace_skill_tags(conn, *, skill_id: int, tags: list[str]) -> None:
        for tag in tags:
            conn.execute(
                """
                INSERT INTO skill_tags (skill_id, tag)
                VALUES (?, ?)
                ON CONFLICT(skill_id, tag) DO NOTHING
                """,
                (skill_id, tag),
            )

    @staticmethod
    def _split_values(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [item for item in raw.split(",") if item]

    @staticmethod
    def _sort_tags(tags: list[str]) -> list[str]:
        built_in = [tag for tag in ALLOWED_TAGS if tag in tags]
        custom = [tag for tag in tags if tag not in built_in]
        return [*built_in, *custom]

    def _write_archive(self, slug: str, archive_bytes: bytes) -> Path:
        archive_path = ARCHIVES_DIR / f"{slug}.zip"
        archive_path.write_bytes(archive_bytes)
        return archive_path

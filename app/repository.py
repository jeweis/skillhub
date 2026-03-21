import io
import re
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import ARCHIVES_DIR
from app.database import Database
from app.models import (
    SkillArchiveMetadata,
    SkillDetail,
    SkillListItem,
    SkillPreviewFile,
    SkillUploadResponse,
)

PREVIEW_BASENAMES = ("SKILL.md", "README.md", "REFERENCE.md")


class SkillRepository:
    def __init__(self, database: Database):
        self.database = database

    def list_skills(self, query: str | None = None) -> list[SkillListItem]:
        sql = """
            SELECT s.id, s.slug, s.name, s.description, s.archive_filename,
                   s.downloads, s.created_at,
                   GROUP_CONCAT(spf.path, '||') AS preview_paths
            FROM skills s
            LEFT JOIN skill_preview_files spf ON spf.skill_id = s.id
            WHERE 1 = 1
        """
        params: list[object] = []
        if query:
            sql += """
                AND (
                    s.name LIKE ?
                    OR s.slug LIKE ?
                    OR s.description LIKE ?
                )
            """
            needle = f"%{query.strip()}%"
            params.extend([needle, needle, needle])
        sql += """
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """
        with self.database.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            SkillListItem.model_validate(
                {
                    **dict(row),
                    "preview_paths": self._split_preview_paths(row["preview_paths"]),
                }
            )
            for row in rows
        ]

    def get_skill_detail(self, slug: str) -> SkillDetail:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, slug, name, description, archive_filename,
                       downloads, created_at, updated_at
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
        preview_files = [SkillPreviewFile.model_validate(dict(item)) for item in preview_rows]
        return SkillDetail.model_validate(
            {
                **dict(row),
                "preview_paths": [item.path for item in preview_files],
                "preview_files": preview_files,
            }
        )

    def get_archive_metadata(self, slug: str) -> SkillArchiveMetadata:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT slug, archive_filename
                FROM skills
                WHERE slug = ?
                """,
                (slug,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Skill not found")
        return SkillArchiveMetadata(
            skill_slug=row["slug"],
            archive_filename=row["archive_filename"],
            download_url=f"/api/skills/{row['slug']}/download",
        )

    async def inspect_skill_archive(self, upload: UploadFile) -> SkillUploadResponse:
        filename = upload.filename or "skill.zip"
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip uploads are supported")

        archive_bytes = await upload.read()
        if not archive_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        parsed = self._parse_skill_archive(archive_bytes)
        slug = self._slugify(parsed["name"])
        return SkillUploadResponse(
            slug=slug,
            name=parsed["name"],
            description=parsed["description"],
            preview_paths=[item["path"] for item in parsed["preview_files"]],
        )

    async def create_skill_from_zip(self, upload: UploadFile) -> SkillUploadResponse:
        filename = upload.filename or "skill.zip"
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip uploads are supported")

        archive_bytes = await upload.read()
        if not archive_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        parsed = self._parse_skill_archive(archive_bytes)
        slug = self._slugify(parsed["name"])
        archive_path = self._write_archive(slug, filename, archive_bytes)

        try:
            with self.database.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO skills (
                        slug, name, description, archive_filename, archive_path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        slug,
                        parsed["name"],
                        parsed["description"],
                        Path(filename).name,
                        str(archive_path),
                    ),
                )
                skill_id = cursor.lastrowid
                for preview_file in parsed["preview_files"]:
                    conn.execute(
                        """
                        INSERT INTO skill_preview_files (skill_id, path, content)
                        VALUES (?, ?, ?)
                        """,
                        (skill_id, preview_file["path"], preview_file["content"]),
                    )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

        return SkillUploadResponse(
            slug=slug,
            name=parsed["name"],
            description=parsed["description"],
            preview_paths=[item["path"] for item in parsed["preview_files"]],
        )

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

    def _parse_skill_archive(self, archive_bytes: bytes) -> dict[str, object]:
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                entries = self._collect_preview_files(archive)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid zip file") from exc

        skill_md = entries.get("SKILL.md")
        if skill_md is None:
            raise HTTPException(status_code=400, detail="SKILL.md is required in the zip archive")

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
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", skill_md, re.DOTALL)
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
        cleaned = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", markdown, flags=re.DOTALL).strip()
        cleaned = re.sub(r"^#\s+.+$", "", cleaned, count=1, flags=re.MULTILINE).strip()
        parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        return parts[0] if parts else "No description provided."

    @staticmethod
    def _slugify(value: str) -> str:
        lowered = value.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return slug or "untitled-skill"

    @staticmethod
    def _split_preview_paths(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [item for item in raw.split("||") if item]

    def _write_archive(self, slug: str, filename: str, archive_bytes: bytes) -> Path:
        archive_path = ARCHIVES_DIR / f"{slug}.zip"
        archive_path.write_bytes(archive_bytes)
        return archive_path

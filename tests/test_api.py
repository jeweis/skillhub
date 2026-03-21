import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.main import app
from app.repository import SkillRepository


def make_test_client(tmp_path: Path) -> TestClient:
    database = Database(tmp_path / "test.db")
    database.initialize()
    app.dependency_overrides = {}
    import app.main as main_module

    main_module.database = database
    main_module.repository = SkillRepository(database)
    return TestClient(app)


def build_skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "SKILL.md",
            """---
name: Prompt QA Kit
description: Use when evaluating prompt regressions and reviewing expectation drift.
---

# Prompt QA Kit

Use this skill to compare prompts, assertions, and regression output.
""",
        )
        archive.writestr("README.md", "# README\n\nMore context for the skill.")
        archive.writestr("REFERENCE.md", "# Reference\n\nExtra usage notes.")
    return buffer.getvalue()


def test_list_skills_empty_before_upload(tmp_path: Path):
    client = make_test_client(tmp_path)
    response = client.get("/api/skills")
    assert response.status_code == 200
    assert response.json() == []


def test_upload_skill_zip_and_list_it(tmp_path: Path):
    client = make_test_client(tmp_path)
    response = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["slug"] == "prompt-qa-kit"
    assert payload["name"] == "Prompt QA Kit"
    assert "SKILL.md" in payload["preview_paths"]

    list_response = client.get("/api/skills")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["slug"] == "prompt-qa-kit"


def test_inspect_skill_zip_without_persisting(tmp_path: Path):
    client = make_test_client(tmp_path)
    inspect_response = client.post(
        "/api/skills/inspect",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
    )
    assert inspect_response.status_code == 200
    assert inspect_response.json()["slug"] == "prompt-qa-kit"

    list_response = client.get("/api/skills")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_get_skill_detail_returns_markdown_previews(tmp_path: Path):
    client = make_test_client(tmp_path)
    client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
    )
    response = client.get("/api/skills/prompt-qa-kit")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Prompt QA Kit"
    assert len(payload["preview_files"]) == 3
    assert payload["preview_files"][0]["path"] == "SKILL.md"


def test_archive_metadata_and_download(tmp_path: Path):
    client = make_test_client(tmp_path)
    client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
    )

    archive_response = client.get("/api/skills/prompt-qa-kit/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["download_url"] == "/api/skills/prompt-qa-kit/download"

    download_response = client.get("/api/skills/prompt-qa-kit/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("application/zip")

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth_service import AuthService
from app.database import Database
from app.feishu_auth_service import FeishuAuthService
from app.feishu_settings_service import FeishuSettingsService
from app.main import app
from app.repository import SkillRepository


def make_test_client(tmp_path: Path) -> TestClient:
    database = Database(tmp_path / "test.db")
    database.initialize()
    app.dependency_overrides = {}
    import app.main as main_module

    main_module.database = database
    main_module.repository = SkillRepository(database)
    main_module.auth_service = AuthService(database)
    main_module.feishu_settings_service = FeishuSettingsService(database)
    main_module.feishu_auth_service = FeishuAuthService()
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


def bootstrap_and_login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_bootstrap_status_requires_setup_initially(tmp_path: Path):
    client = make_test_client(tmp_path)
    response = client.get("/api/auth/bootstrap-status")
    assert response.status_code == 200
    assert response.json() == {"requires_setup": True}


def test_bootstrap_creates_admin_and_returns_session(tmp_path: Path):
    client = make_test_client(tmp_path)
    response = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "password": "password123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["role"] == "admin"
    assert payload["token"]

    second_status = client.get("/api/auth/bootstrap-status")
    assert second_status.json() == {"requires_setup": False}


def test_publish_requires_login(tmp_path: Path):
    client = make_test_client(tmp_path)
    response = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
    )
    assert response.status_code == 401


def test_upload_skill_zip_and_list_it(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    response = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
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
    assert list_payload[0]["publisher_name"] == "admin"


def test_inspect_skill_zip_without_persisting(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    inspect_response = client.post(
        "/api/skills/inspect",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert inspect_response.status_code == 200
    assert inspect_response.json()["slug"] == "prompt-qa-kit"

    list_response = client.get("/api/skills")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_get_skill_detail_returns_markdown_previews(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    response = client.get("/api/skills/prompt-qa-kit")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Prompt QA Kit"
    assert len(payload["preview_files"]) == 3
    assert payload["preview_files"][0]["path"] == "SKILL.md"


def test_archive_metadata_and_download(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )

    archive_response = client.get("/api/skills/prompt-qa-kit/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["download_url"] == "/api/skills/prompt-qa-kit/download"

    download_response = client.get("/api/skills/prompt-qa-kit/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("application/zip")


def test_admin_can_update_feishu_settings(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    response = client.put(
        "/api/admin/feishu-settings",
        json={
            "enabled": True,
            "app_id": "cli_test",
            "app_secret": "secret-value",
            "base_url": "https://open.feishu.cn",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["app_id"] == "cli_test"
    assert payload["has_app_secret"] is True

    public_status = client.get("/api/auth/feishu/status")
    assert public_status.status_code == 200
    assert public_status.json()["enabled"] is True


def test_admin_can_create_and_list_users(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    create_response = client.post(
        "/api/admin/users",
        json={
            "username": "creator01",
            "password": "password123",
            "display_name": "Skill Creator",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["username"] == "creator01"
    assert create_response.json()["role"] == "member"

    list_response = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    usernames = {item["username"] for item in items}
    assert {"admin", "creator01"}.issubset(usernames)

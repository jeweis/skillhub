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
from app.search_settings_service import SearchSettingsService
from app.vector_search_service import VectorSearchService


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
    main_module.search_settings_service = SearchSettingsService(database)
    main_module.vector_search_service = VectorSearchService(
        database,
        main_module.search_settings_service,
    )
    return TestClient(app)


def build_skill_zip(
    *,
    name: str = "Prompt QA Kit",
    description: str = (
        "Use when evaluating prompt regressions and reviewing expectation drift."
    ),
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "SKILL.md",
            f"""---
name: {name}
description: {description}
---

# {name}

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
    assert list_payload[0]["tags"] == []


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
    assert payload["tags"] == []


def test_upload_rejects_duplicate_skill_name(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    files = {"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")}
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/api/skills", files=files, headers=headers)
    assert first.status_code == 201

    second = client.post("/api/skills", files=files, headers=headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "skill_exists_owned"
    assert second.json()["detail"]["can_overwrite"] is True


def test_owner_can_overwrite_existing_skill(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers=headers,
    )
    assert first.status_code == 201

    overwrite = client.post(
        "/api/skills",
        data={"overwrite": "true"},
        files={
            "file": (
                "prompt-qa-kit.zip",
                build_skill_zip(description="Updated description for overwrite."),
                "application/zip",
            )
        },
        headers=headers,
    )
    assert overwrite.status_code == 201
    assert overwrite.json()["slug"] == "prompt-qa-kit"

    detail = client.get("/api/skills/prompt-qa-kit")
    assert detail.status_code == 200
    assert detail.json()["description"] == "Updated description for overwrite."


def test_duplicate_name_from_another_user_is_rejected(tmp_path: Path):
    client = make_test_client(tmp_path)
    admin_token = bootstrap_and_login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers=headers,
    )
    assert first.status_code == 201

    create_response = client.post(
        "/api/admin/users",
        json={
            "username": "creator02",
            "password": "password123",
            "display_name": "Another Creator",
        },
        headers=headers,
    )
    assert create_response.status_code == 201

    member_login = client.post(
        "/api/auth/login",
        json={"username": "creator02", "password": "password123"},
    )
    member_token = member_login.json()["token"]

    denied = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "同名 Skill 已存在，不能重复上传"


def test_admin_can_update_search_settings(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)

    response = client.put(
        "/api/admin/search-settings",
        json={
            "enabled": True,
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "bge-m3",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["provider"] == "ollama"
    assert payload["model"] == "bge-m3"
    assert payload["configured"] is True


def test_search_falls_back_to_keyword_when_vector_search_unavailable(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    response = client.post(
        "/api/skills",
        files={
            "file": (
                "excel.zip",
                build_skill_zip(
                    name="Excel Assistant",
                    description="Analyze xlsx workbooks and formulas.",
                ),
                "application/zip",
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201

    search = client.get("/api/skills/search?q=Excel")
    assert search.status_code == 200
    assert search.json()[0]["name"] == "Excel Assistant"


def test_search_uses_vector_order_when_available(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(
        "/api/skills",
        files={
            "file": (
                "alpha.zip",
                build_skill_zip(name="Alpha Skill", description="First"),
                "application/zip",
            )
        },
        headers=headers,
    )
    second = client.post(
        "/api/skills",
        files={
            "file": (
                "beta.zip",
                build_skill_zip(name="Beta Skill", description="Second"),
                "application/zip",
            )
        },
        headers=headers,
    )
    assert first.status_code == 201
    assert second.status_code == 201

    class FakeVectorSearchService:
        def search_skill_ids(self, query, repository):
            del query, repository
            return [2, 1]

        def index_skill_by_slug(self, slug, repository):
            del slug, repository

        def reindex_all_skills(self, repository):
            del repository
            return 0

    import app.main as main_module

    original_service = main_module.vector_search_service
    main_module.vector_search_service = FakeVectorSearchService()
    try:
        search = client.get("/api/skills/search?q=anything")
        assert search.status_code == 200
        payload = search.json()
        assert payload[0]["name"] == "Beta Skill"
        assert payload[1]["name"] == "Alpha Skill"
    finally:
        main_module.vector_search_service = original_service


def test_member_can_set_regular_tags_but_not_recommended(tmp_path: Path):
    client = make_test_client(tmp_path)
    admin_token = bootstrap_and_login(client)
    create_response = client.post(
        "/api/admin/users",
        json={
            "username": "creator01",
            "password": "password123",
            "display_name": "Skill Creator",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_response.status_code == 201
    member_login = client.post(
        "/api/auth/login",
        json={"username": "creator01", "password": "password123"},
    )
    token = member_login.json()["token"]

    tagged_response = client.post(
        "/api/skills",
        data={"tags_json": '["热门","研发"]'},
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tagged_response.status_code == 201
    assert tagged_response.json()["tags"] == ["热门", "研发"]

    denied_response = client.post(
        "/api/skills",
        data={"tags_json": '["推荐"]'},
        files={
            "file": (
                "prompt-qa-kit-recommended.zip",
                build_skill_zip(name="Prompt QA Kit Recommended"),
                "application/zip",
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied_response.status_code == 403
    assert denied_response.json()["detail"] == "推荐标签只能由管理员添加"


def test_upload_supports_custom_tags(tmp_path: Path):
    client = make_test_client(tmp_path)
    token = bootstrap_and_login(client)

    response = client.post(
        "/api/skills",
        data={"tags_json": '["热门","工作流","提示词"]'},
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["tags"] == ["热门", "工作流", "提示词"]

    detail = client.get("/api/skills/prompt-qa-kit")
    assert detail.status_code == 200
    assert detail.json()["tags"] == ["热门", "工作流", "提示词"]


def test_admin_can_add_recommended_tag_to_any_skill(tmp_path: Path):
    client = make_test_client(tmp_path)
    admin_token = bootstrap_and_login(client)
    create_response = client.post(
        "/api/admin/users",
        json={
            "username": "creator01",
            "password": "password123",
            "display_name": "Skill Creator",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_response.status_code == 201

    member_login = client.post(
        "/api/auth/login",
        json={"username": "creator01", "password": "password123"},
    )
    member_token = member_login.json()["token"]

    upload_response = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert upload_response.status_code == 201

    recommend_response = client.post(
        "/api/skills/prompt-qa-kit/recommended",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert recommend_response.status_code == 200
    assert recommend_response.json()["tags"] == ["推荐"]


def test_owner_can_delete_own_skill_but_not_others(tmp_path: Path):
    client = make_test_client(tmp_path)
    admin_token = bootstrap_and_login(client)
    client.post(
        "/api/admin/users",
        json={
            "username": "creator01",
            "password": "password123",
            "display_name": "Skill Creator",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    client.post(
        "/api/admin/users",
        json={
            "username": "creator02",
            "password": "password123",
            "display_name": "Other Creator",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    member_one = client.post(
        "/api/auth/login",
        json={"username": "creator01", "password": "password123"},
    )
    token_one = member_one.json()["token"]

    member_two = client.post(
        "/api/auth/login",
        json={"username": "creator02", "password": "password123"},
    )
    token_two = member_two.json()["token"]

    upload_response = client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {token_one}"},
    )
    assert upload_response.status_code == 201

    forbidden_delete = client.delete(
        "/api/skills/prompt-qa-kit",
        headers={"Authorization": f"Bearer {token_two}"},
    )
    assert forbidden_delete.status_code == 403

    owner_delete = client.delete(
        "/api/skills/prompt-qa-kit",
        headers={"Authorization": f"Bearer {token_one}"},
    )
    assert owner_delete.status_code == 200
    assert owner_delete.json()["message"] == "Skill 已删除"

    list_response = client.get("/api/skills")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_admin_can_delete_any_skill(tmp_path: Path):
    client = make_test_client(tmp_path)
    admin_token = bootstrap_and_login(client)
    client.post(
        "/api/admin/users",
        json={
            "username": "creator01",
            "password": "password123",
            "display_name": "Skill Creator",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    member_login = client.post(
        "/api/auth/login",
        json={"username": "creator01", "password": "password123"},
    )
    member_token = member_login.json()["token"]

    client.post(
        "/api/skills",
        files={"file": ("prompt-qa-kit.zip", build_skill_zip(), "application/zip")},
        headers={"Authorization": f"Bearer {member_token}"},
    )

    delete_response = client.delete(
        "/api/skills/prompt-qa-kit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Skill 已删除"


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

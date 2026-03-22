from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from app.feishu_settings_service import FeishuSettingsService

from app.database import Database
from app.models import SearchSettingsUpdateRequest, SearchSettingsView


@dataclass(frozen=True)
class SearchSettings:
    enabled: bool
    provider: str
    base_url: str
    model: str | None
    basic_auth_username: str | None
    basic_auth_password: str | None

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.provider == "ollama"
            and self.base_url.strip()
            and (self.model or "").strip()
        )


class SearchSettingsService:
    _KEY_ENABLED = "SEARCH_EMBEDDING_ENABLED"
    _KEY_PROVIDER = "SEARCH_EMBEDDING_PROVIDER"
    _KEY_BASE_URL = "SEARCH_EMBEDDING_BASE_URL"
    _KEY_MODEL = "SEARCH_EMBEDDING_MODEL"
    _KEY_BASIC_AUTH_USERNAME = "SEARCH_EMBEDDING_BASIC_AUTH_USERNAME"
    _KEY_BASIC_AUTH_PASSWORD = "SEARCH_EMBEDDING_BASIC_AUTH_PASSWORD_ENCRYPTED"

    def __init__(self, database: Database):
        self.database = database
        self._crypto = FeishuSettingsService(database)

    def get_settings_view(self) -> SearchSettingsView:
        config = self.get_active_config()
        return SearchSettingsView(
            enabled=config.enabled,
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            basic_auth_username=config.basic_auth_username,
            has_basic_auth_password=bool(config.basic_auth_password),
            configured=config.configured,
        )

    def get_active_config(self) -> SearchSettings:
        enabled = (self._get_setting(self._KEY_ENABLED) or "false").lower() == "true"
        provider = (self._get_setting(self._KEY_PROVIDER) or "ollama").strip().lower()
        base_url = (self._get_setting(self._KEY_BASE_URL) or "http://127.0.0.1:11434").strip()
        model = self._normalize(self._get_setting(self._KEY_MODEL))
        basic_auth_username = self._normalize(
            self._get_setting(self._KEY_BASIC_AUTH_USERNAME)
        )
        encoded_password = self._normalize(
            self._get_setting(self._KEY_BASIC_AUTH_PASSWORD)
        )
        basic_auth_password = (
            self._crypto._decrypt(encoded_password) if encoded_password else None
        )
        return SearchSettings(
            enabled=enabled,
            provider=provider or "ollama",
            base_url=base_url.rstrip("/"),
            model=model,
            basic_auth_username=basic_auth_username,
            basic_auth_password=basic_auth_password,
        )

    def update_settings(self, body: SearchSettingsUpdateRequest) -> SearchSettingsView:
        provider = (body.provider or "ollama").strip().lower()
        if provider != "ollama":
            raise HTTPException(status_code=400, detail="当前仅支持 Ollama")

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as conn:
            self._upsert_setting(
                conn, self._KEY_ENABLED, "true" if body.enabled else "false", now
            )
            self._upsert_setting(conn, self._KEY_PROVIDER, provider, now)
            self._upsert_setting(
                conn,
                self._KEY_BASE_URL,
                ((body.base_url or "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434").rstrip("/"),
                now,
            )
            self._upsert_setting(
                conn,
                self._KEY_MODEL,
                self._normalize(body.model) or "",
                now,
            )
            self._upsert_setting(
                conn,
                self._KEY_BASIC_AUTH_USERNAME,
                self._normalize(body.basic_auth_username) or "",
                now,
            )
            if body.basic_auth_password is not None:
                normalized = self._normalize(body.basic_auth_password)
                encrypted = (
                    self._crypto._encrypt(normalized, conn=conn)
                    if normalized
                    else ""
                )
                self._upsert_setting(
                    conn,
                    self._KEY_BASIC_AUTH_PASSWORD,
                    encrypted,
                    now,
                )
        return self.get_settings_view()

    def _upsert_setting(self, conn, key: str, value: str, now: str) -> None:
        conn.execute(
            """
            INSERT INTO system_settings (key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now, now),
        )

    def _get_setting(self, key: str) -> str | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["value"])

    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

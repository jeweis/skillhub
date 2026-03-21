from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from app.database import Database
from app.models import FeishuSettingsView, FeishuStatusResponse


@dataclass(frozen=True)
class FeishuSettings:
    enabled: bool
    app_id: str | None
    app_secret: str | None
    base_url: str


class FeishuSettingsService:
    _KEY_ENABLED = "FEISHU_ENABLED"
    _KEY_APP_ID = "FEISHU_APP_ID"
    _KEY_APP_SECRET = "FEISHU_APP_SECRET_ENCRYPTED"
    _KEY_BASE_URL = "FEISHU_BASE_URL"
    _KEY_APP_SECRET_KEY = "APP_SECRET_KEY"

    def __init__(self, database: Database):
        self.database = database

    def get_public_status(self) -> FeishuStatusResponse:
        config = self.get_active_config()
        enabled = config.enabled and bool(config.app_id) and bool(config.app_secret)
        return FeishuStatusResponse(
            enabled=enabled,
            app_id=config.app_id if enabled else None,
        )

    def get_settings_view(self) -> FeishuSettingsView:
        config = self.get_active_config()
        return FeishuSettingsView(
            enabled=config.enabled,
            app_id=config.app_id,
            has_app_secret=bool(config.app_secret),
            base_url=config.base_url,
        )

    def get_active_config(self) -> FeishuSettings:
        enabled = (self._get_setting(self._KEY_ENABLED) or "false").lower() == "true"
        app_id = self._normalize(self._get_setting(self._KEY_APP_ID))
        encoded_secret = self._normalize(self._get_setting(self._KEY_APP_SECRET))
        base_url = self._normalize(self._get_setting(self._KEY_BASE_URL))
        app_secret = self._decrypt(encoded_secret) if encoded_secret else None
        return FeishuSettings(
            enabled=enabled,
            app_id=app_id,
            app_secret=app_secret,
            base_url=(base_url or "https://open.feishu.cn").rstrip("/"),
        )

    def update_settings(
        self,
        *,
        enabled: bool,
        app_id: str | None,
        app_secret: str | None,
        base_url: str,
    ) -> FeishuSettingsView:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as conn:
            self._upsert_setting(
                conn, self._KEY_ENABLED, "true" if enabled else "false", now
            )
            self._upsert_setting(
                conn, self._KEY_APP_ID, self._normalize(app_id) or "", now
            )
            self._upsert_setting(
                conn,
                self._KEY_BASE_URL,
                (self._normalize(base_url) or "https://open.feishu.cn").rstrip("/"),
                now,
            )
            if app_secret is not None:
                normalized = self._normalize(app_secret)
                encrypted = self._encrypt(normalized, conn=conn) if normalized else ""
                self._upsert_setting(conn, self._KEY_APP_SECRET, encrypted, now)
        return self.get_settings_view()

    def assert_login_enabled(self) -> FeishuSettings:
        config = self.get_active_config()
        if not config.enabled:
            raise HTTPException(status_code=400, detail="飞书登录尚未启用")
        if not config.app_id or not config.app_secret:
            raise HTTPException(status_code=400, detail="飞书登录配置还不完整")
        return config

    def build_authorize_url(self, redirect_uri: str | None = None) -> str:
        config = self.assert_login_enabled()
        callback = (redirect_uri or "").strip()
        if not callback:
            raise HTTPException(status_code=400, detail="缺少飞书登录回调地址")
        query = urllib.parse.urlencode(
            {
                "app_id": config.app_id,
                "redirect_uri": callback,
                "response_type": "code",
                "scope": "contact:user.base:readonly",
            }
        )
        return f"{config.base_url}/open-apis/authen/v1/authorize?{query}"

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

    def _resolve_crypto_key(self, conn=None) -> bytes:
        env_key = os.getenv("APP_SECRET_KEY", "").strip()
        if env_key:
            return env_key.encode("utf-8")
        if conn is not None:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (self._KEY_APP_SECRET_KEY,),
            ).fetchone()
            if row is not None:
                return str(row["value"]).encode("utf-8")
            generated = secrets.token_urlsafe(48)
            now = datetime.now(timezone.utc).isoformat()
            self._upsert_setting(conn, self._KEY_APP_SECRET_KEY, generated, now)
            return generated.encode("utf-8")
        with self.database.connect() as managed_conn:
            return self._resolve_crypto_key(conn=managed_conn)

    def _encrypt(self, plain: str | None, conn=None) -> str | None:
        if plain is None:
            return None
        key = self._resolve_crypto_key(conn=conn)
        nonce = os.urandom(16)
        raw = plain.encode("utf-8")
        encrypted = bytes(
            value ^ self._keystream_byte(key, nonce, index)
            for index, value in enumerate(raw)
        )
        tag = hmac.new(key, nonce + encrypted, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + encrypted).decode("utf-8")

    def _decrypt(self, encoded: str | None) -> str | None:
        if not encoded:
            return None
        try:
            raw = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="飞书密钥解密失败") from exc
        if len(raw) < 48:
            raise HTTPException(status_code=400, detail="飞书密钥格式不正确")
        nonce = raw[:16]
        tag = raw[16:48]
        encrypted = raw[48:]
        key = self._resolve_crypto_key()
        expected = hmac.new(key, nonce + encrypted, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, tag):
            raise HTTPException(status_code=400, detail="飞书密钥签名校验失败")
        plain = bytes(
            value ^ self._keystream_byte(key, nonce, index)
            for index, value in enumerate(encrypted)
        )
        return plain.decode("utf-8")

    @staticmethod
    def _keystream_byte(key: bytes, nonce: bytes, index: int) -> int:
        block = index // 32
        offset = index % 32
        material = nonce + block.to_bytes(8, "big")
        return hashlib.sha256(key + material).digest()[offset]

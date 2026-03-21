from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from fastapi import HTTPException


@dataclass(frozen=True)
class FeishuUserInfo:
    union_id: str
    open_id: str | None
    name: str
    avatar_url: str | None


class FeishuAuthService:
    def exchange_code(
        self,
        *,
        base_url: str,
        app_id: str,
        app_secret: str,
        code: str,
    ) -> str:
        payload = {
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
        }
        data = self._post_json(
            f"{base_url.rstrip('/')}/open-apis/authen/v2/oauth/token",
            payload,
        )
        self._assert_success(data)
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status_code=400, detail="飞书登录令牌缺失")
        return access_token

    def get_user_info(
        self,
        *,
        base_url: str,
        user_access_token: str,
    ) -> FeishuUserInfo:
        data = self._get_json(
            f"{base_url.rstrip('/')}/open-apis/authen/v1/user_info",
            headers={
                "Authorization": f"Bearer {user_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        self._assert_success(data)
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="飞书用户信息返回格式不正确")
        union_id = payload.get("union_id")
        if not isinstance(union_id, str) or not union_id:
            raise HTTPException(status_code=400, detail="飞书用户缺少 union_id")
        name = payload.get("name")
        return FeishuUserInfo(
            union_id=union_id,
            open_id=payload.get("open_id")
            if isinstance(payload.get("open_id"), str)
            else None,
            name=name if isinstance(name, str) and name else "飞书用户",
            avatar_url=payload.get("avatar_url")
            if isinstance(payload.get("avatar_url"), str)
            else None,
        )

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._open_json(req)

    def _get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        req = request.Request(url=url, headers=headers, method="GET")
        return self._open_json(req)

    def _open_json(self, req: request.Request) -> dict[str, Any]:
        try:
            with request.urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=400,
                detail=f"飞书接口请求失败: {body or exc.reason}",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"无法访问飞书接口: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="飞书接口返回了无效 JSON") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="飞书接口返回格式不正确")
        return parsed

    @staticmethod
    def _assert_success(payload: dict[str, Any]) -> None:
        if payload.get("code") == 0:
            return
        raise HTTPException(status_code=400, detail="飞书接口返回了错误结果")

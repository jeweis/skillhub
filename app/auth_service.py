import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.database import Database
from app.models import AuthUser

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_PBKDF2_ITERATIONS = 200_000


@dataclass(frozen=True)
class AuthSession:
    token: str
    user: AuthUser


class AuthService:
    def __init__(self, database: Database, token_ttl_hours: int = 24 * 14):
        self.database = database
        self.token_ttl_hours = token_ttl_hours

    def requires_bootstrap(self) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT COUNT(1) AS c FROM users").fetchone()
        return int(row["c"]) == 0

    def bootstrap_admin(self, username: str, password: str) -> AuthSession:
        if not self.requires_bootstrap():
            raise HTTPException(status_code=409, detail="管理员账号已经创建")
        self._validate_username(username)
        self._validate_password(password)

        now = self._now()
        password_hash = self._hash_password(password)
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, role, display_name, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (username, password_hash, "admin", username, now),
            )
            user = AuthUser(
                id=int(cursor.lastrowid),
                username=username,
                role="admin",
                display_name=username,
                created_at=datetime.fromisoformat(now),
            )
            token = self._create_token(conn, user.id, now)
        return AuthSession(token=token, user=user)

    def login(self, username: str, password: str) -> AuthSession:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, password_hash, role, display_name, created_at
                FROM users
                WHERE username = ?
                """,
                (username.strip(),),
            ).fetchone()
            if row is None or not self._verify_password(
                password, str(row["password_hash"])
            ):
                raise HTTPException(status_code=401, detail="用户名或密码不正确")
            now = self._now()
            token = self._create_token(conn, int(row["id"]), now)
        return AuthSession(
            token=token,
            user=self._build_user(row),
        )

    def login_by_feishu(
        self,
        *,
        union_id: str,
        open_id: str | None,
        name: str,
        avatar_url: str | None = None,
    ) -> AuthSession:
        del avatar_url
        now = self._now()
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, role, display_name, created_at
                FROM users
                WHERE feishu_union_id = ?
                LIMIT 1
                """,
                (union_id,),
            ).fetchone()
            if row is None:
                username = self._generate_feishu_username(conn, name)
                cursor = conn.execute(
                    """
                    INSERT INTO users (
                        username,
                        password_hash,
                        role,
                        display_name,
                        created_at,
                        feishu_union_id,
                        feishu_open_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        self._hash_password(secrets.token_urlsafe(32)),
                        "member",
                        name.strip() or username,
                        now,
                        union_id,
                        open_id,
                    ),
                )
                user = AuthUser(
                    id=int(cursor.lastrowid),
                    username=username,
                    role="member",
                    display_name=name.strip() or username,
                    created_at=datetime.fromisoformat(now),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, feishu_open_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name.strip() or row["username"], open_id, now, row["id"]),
                )
                refreshed = conn.execute(
                    """
                    SELECT id, username, role, display_name, created_at
                    FROM users
                    WHERE id = ?
                    """,
                    (row["id"],),
                ).fetchone()
                user = self._build_user(refreshed)
            token = self._create_token(conn, user.id, now)
        return AuthSession(token=token, user=user)

    def get_user_by_token(self, token: str) -> AuthUser:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.token,
                    t.expires_at,
                    u.id,
                    u.username,
                    u.role,
                    u.display_name,
                    u.created_at
                FROM auth_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.token = ?
                """,
                (token,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail="请先登录")
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
            if expires_at < datetime.now(timezone.utc):
                conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
                raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        return self._build_user(row)

    def revoke_token(self, token: str) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))

    def assert_admin(self, user: AuthUser) -> None:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以执行这个操作")

    def list_users(self) -> list[AuthUser]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, role, display_name, created_at
                FROM users
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._build_user(row) for row in rows]

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None,
    ) -> AuthUser:
        self._validate_username(username)
        self._validate_password(password)
        now = self._now()
        normalized_display_name = (display_name or "").strip() or username.strip()
        password_hash = self._hash_password(password)
        try:
            with self.database.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (
                        username,
                        password_hash,
                        role,
                        display_name,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        username.strip(),
                        password_hash,
                        "member",
                        normalized_display_name,
                        now,
                    ),
                )
        except Exception as exc:
            if "UNIQUE constraint failed: users.username" in str(exc):
                raise HTTPException(status_code=409, detail="这个用户名已经存在") from exc
            raise
        return AuthUser(
            id=int(cursor.lastrowid),
            username=username.strip(),
            role="member",
            display_name=normalized_display_name,
            created_at=datetime.fromisoformat(now),
        )

    def _build_user(self, row) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            display_name=row["display_name"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _create_token(self, conn, user_id: int, now: str) -> str:
        token = secrets.token_urlsafe(48)
        expires_at = (
            datetime.fromisoformat(now)
            + timedelta(hours=self.token_ttl_hours)
        ).isoformat()
        conn.execute(
            """
            INSERT INTO auth_tokens (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, now, expires_at),
        )
        return token

    @staticmethod
    def _validate_username(username: str) -> None:
        if not _USERNAME_PATTERN.match(username.strip()):
            raise HTTPException(
                status_code=400,
                detail="用户名需为 3-32 位，仅支持字母、数字、点、下划线和中划线",
            )

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="密码至少需要 8 位")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            _PBKDF2_ITERATIONS,
        ).hex()
        return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"

    def _verify_password(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt, digest = encoded.split("$", 3)
        except ValueError:
            return False
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)

    def _generate_feishu_username(self, conn, name: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        prefix = normalized[:20] or "feishu-user"
        candidate = prefix
        index = 1
        while True:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate
            index += 1
            candidate = f"{prefix}-{index}"

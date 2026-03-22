from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone

from app.repository import SkillRepository
from app.search_settings_service import SearchSettings, SearchSettingsService


class VectorSearchService:
    def __init__(
        self,
        database,
        settings_service: SearchSettingsService,
    ):
        self.database = database
        self.settings_service = settings_service

    def search_skill_ids(self, query: str, repository: SkillRepository) -> list[int] | None:
        config = self.settings_service.get_active_config()
        if not config.configured:
            return None

        try:
            query_vector = self._embed(config, query.strip())
            candidates = self._load_embeddings(config)
            if not candidates:
                self.reindex_all_skills(repository)
                candidates = self._load_embeddings(config)
            if not candidates:
                return None

            scored: list[tuple[int, float]] = []
            for skill_id, vector in candidates:
                score = self._cosine_similarity(query_vector, vector)
                if score is None:
                    continue
                scored.append((skill_id, score))

            scored.sort(key=lambda item: item[1], reverse=True)
            skill_ids = [skill_id for skill_id, score in scored if score > 0]
            return skill_ids or None
        except Exception:
            return None

    def index_skill_by_slug(self, slug: str, repository: SkillRepository) -> None:
        config = self.settings_service.get_active_config()
        if not config.configured:
            return
        document = repository.get_search_document_by_slug(slug)
        if document is None:
            return
        self._upsert_embedding(
            config=config,
            skill_id=document["skill_id"],
            content=document["content"],
        )

    def reindex_all_skills(self, repository: SkillRepository) -> int:
        config = self.settings_service.get_active_config()
        if not config.configured:
            return 0
        count = 0
        for document in repository.list_search_documents():
            self._upsert_embedding(
                config=config,
                skill_id=document["skill_id"],
                content=document["content"],
            )
            count += 1
        return count

    def _upsert_embedding(
        self,
        *,
        config: SearchSettings,
        skill_id: int,
        content: str,
    ) -> None:
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = self._get_embedding_meta(skill_id)
        if existing == (config.provider, config.model, source_hash):
            return

        vector = self._embed(config, content)
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_embeddings (
                    skill_id,
                    provider,
                    model,
                    vector_json,
                    source_hash,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    vector_json = excluded.vector_json,
                    source_hash = excluded.source_hash,
                    updated_at = excluded.updated_at
                """,
                (
                    skill_id,
                    config.provider,
                    config.model or "",
                    json.dumps(vector),
                    source_hash,
                    now,
                ),
            )

    def _get_embedding_meta(self, skill_id: int) -> tuple[str, str, str] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT provider, model, source_hash
                FROM skill_embeddings
                WHERE skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["provider"]), str(row["model"]), str(row["source_hash"])

    def _load_embeddings(self, config: SearchSettings) -> list[tuple[int, list[float]]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT skill_id, vector_json
                FROM skill_embeddings
                WHERE provider = ? AND model = ?
                """,
                (config.provider, config.model or ""),
            ).fetchall()
        result: list[tuple[int, list[float]]] = []
        for row in rows:
            try:
                vector = json.loads(str(row["vector_json"]))
            except json.JSONDecodeError:
                continue
            if not isinstance(vector, list):
                continue
            result.append((int(row["skill_id"]), [float(item) for item in vector]))
        return result

    def _embed(self, config: SearchSettings, text: str) -> list[float]:
        if config.provider != "ollama":
            raise ValueError("Unsupported provider")
        return self._embed_with_ollama(config, text)

    def _embed_with_ollama(self, config: SearchSettings, text: str) -> list[float]:
        payload = {
            "model": config.model,
            "input": text,
        }
        try:
            response = self._post_json(
                f"{config.base_url}/api/embed",
                payload,
            )
            embeddings = response.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0]
                if isinstance(first, list):
                    return [float(item) for item in first]
        except Exception:
            pass

        legacy = self._post_json(
            f"{config.base_url}/api/embeddings",
            {"model": config.model, "prompt": text},
        )
        embedding = legacy.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Invalid embedding response")
        return [float(item) for item in embedding]

    @staticmethod
    def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise ValueError(body or f"HTTP {exc.code}") from exc

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float | None:
        if not left or not right or len(left) != len(right):
            return None
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return None
        return numerator / (left_norm * right_norm)

"""Read-only hybrid retrieval over indexed knowledge.

Raw SQL is used deliberately: the retrieval legs mix full-text ranking
(``ts_rank``) and pgvector operators (``<=>``) that the ORM does not express
naturally. Chunk rows are joined to their document, version, and the latest
ingestion job so provenance (parser/chunking/embedding) rides along with
every hit.
"""

import json
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.contracts import IngestionProvenance, RestrictedDocument
from app.knowledge.models import DocumentCategory


def vector_to_text(vector: list[float]) -> str:
    """Render a vector in PostgreSQL's text format, e.g. ``[1.5,2,0]``.

    asyncpg cannot bind a Python ``list[float]`` directly to a ``vector``
    parameter, so we cast the text form: ``(:query_embedding)::vector``.
    """
    return "[" + ",".join(str(x) for x in vector) + "]"


@dataclass(frozen=True)
class RetrievalHit:
    """A raw row returned by a retrieval leg before fusion.

    ``score`` means different things per leg (BM25 rank vs. cosine
    similarity); the caller fuses these, so the legs never compare scores.
    """

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    document_title: str
    category: str
    page: int | None
    section_title: str | None
    content: str
    score: float
    provenance: IngestionProvenance = field(default_factory=IngestionProvenance)

    @property
    def key(self) -> str:
        return str(self.chunk_id)


# Shared FROM/JOIN clause: chunk → version → document, plus the ingestion job
# that produced the version (its status gates what is served).
_JOINS = """
    FROM document_chunk c
    JOIN document_version v ON v.document_version_id = c.document_version_id
    JOIN document d ON d.document_id = v.document_id
    JOIN ingestion_job j ON j.document_version_id = v.document_version_id
"""

# Columns common to both retrieval legs (metadata + provenance, no score).
_SELECT_COLS = """
    SELECT
        c.chunk_id,
        d.document_id,
        v.document_version_id,
        v.version_number,
        d.title,
        d.category,
        c.page_number,
        c.section_title,
        c.content,
        j.parser_version,
        j.chunking_strategy,
        j.embedding_model,
        j.embedding_version,
        j.pipeline_version
"""


class HybridRetrievalRepository:
    """Read-only access to indexed knowledge.

    Only rows whose ``ingestion_job.status`` and
    ``document_version.status`` are ``INDEXED`` are ever served. Query-time
    scores are computed here and never persisted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bm25_search(
        self,
        query: str,
        limit: int,
        *,
        current_only: bool = True,
        category: DocumentCategory | None = None,
        document_type: str | None = None,
        access_roles: list[str] | None = None,
    ) -> list[RetrievalHit]:
        """Lexical leg: PostgreSQL Full-Text Search (BM25 via ``ts_rank``).

        Only embeddable (leaf) rows are searched: document/section context rows
        are not indexed for retrieval, so a whole page that merely mentions a
        phrase cannot crowd out the focused leaf that states it.

        ``access_roles`` restricts results to documents whose ``role_access``
        allowlist contains every requester role; ``None`` disables the filter
        (HR admin / callers not applying access control).
        """
        sql = text(
            _SELECT_COLS
            + f""", ts_rank(to_tsvector('english', c.processed_content),
                              plainto_tsquery('english', :query)) AS score
            {_JOINS}
            WHERE j.status = 'INDEXED'
              AND v.status = 'INDEXED'
              AND d.deleted_at IS NULL
              AND c.embeddable = TRUE
              AND to_tsvector('english', c.processed_content)
                  @@ plainto_tsquery('english', :query)
              AND (:current_only = FALSE OR v.is_current = TRUE)
              {self._filter_clause(category, document_type, access_roles)}
            ORDER BY score DESC
            LIMIT :limit"""
        )
        params: dict = {
            "query": query,
            "current_only": current_only,
            "limit": limit,
        }
        self._add_filter_params(params, category, document_type, access_roles)
        return await self._fetch(sql, params)

    async def vector_search(
        self,
        query_embedding: list[float],
        limit: int,
        *,
        current_only: bool = True,
        category: DocumentCategory | None = None,
        document_type: str | None = None,
        access_roles: list[str] | None = None,
    ) -> list[RetrievalHit]:
        """Semantic leg: pgvector cosine-distance search (``<=>``).

        Score is converted from distance to similarity (``1 - distance``) so
        higher is better, matching the BM25 leg's ordering.
        """
        sql = text(
            _SELECT_COLS
            + f""", 1 - (c.embedding <=> (:query_embedding)::vector) AS score
            {_JOINS}
            WHERE j.status = 'INDEXED'
              AND v.status = 'INDEXED'
              AND d.deleted_at IS NULL
              AND c.embedding IS NOT NULL
              AND (:current_only = FALSE OR v.is_current = TRUE)
              {self._filter_clause(category, document_type, access_roles)}
            ORDER BY c.embedding <=> (:query_embedding)::vector ASC
            LIMIT :limit"""
        )
        params: dict = {
            "query_embedding": vector_to_text(query_embedding),
            "current_only": current_only,
            "limit": limit,
        }
        self._add_filter_params(params, category, document_type, access_roles)
        return await self._fetch(sql, params)

    async def fetch_parent_context(self, chunk_ids: list[UUID]) -> dict[UUID, str]:
        """Small-to-big expansion: enclosing section text for matched leaves.

        Retrieval legs match leaf rows only; the answer needs the section the
        leaf lives in. For each leaf chunk id this returns the text of its
        immediate parent node, restricted to section rows — the document root
        row (whole-document text) is deliberately excluded so the LLM context
        stays focused instead of receiving the entire document per leaf.
        Leaves whose parent is the document root (preamble) simply get no
        expansion; their ``document_title`` metadata already anchors them.
        """
        if not chunk_ids:
            return {}
        sql = text(
            """
            SELECT c.chunk_id AS leaf_id, p.content
            FROM document_chunk c
            JOIN document_chunk p ON p.chunk_id = c.parent_chunk_id
            WHERE c.chunk_id IN :chunk_ids
              AND c.embeddable = TRUE
              AND p.chunk_level = 'section'
            """
        ).bindparams(bindparam("chunk_ids", expanding=True))
        result = await self._session.execute(sql, {"chunk_ids": chunk_ids})
        return {row["leaf_id"]: row["content"] for row in result.mappings()}

    async def _fetch(self, sql: object, params: dict) -> list[RetrievalHit]:
        """Execute a leg's SQL and map rows to ``RetrievalHit`` objects."""
        result = await self._session.execute(sql, params)
        hits: list[RetrievalHit] = []
        for row in result.mappings():
            hits.append(
                RetrievalHit(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    document_version_id=row["document_version_id"],
                    version_number=row["version_number"],
                    document_title=row["title"],
                    category=row["category"].value
                    if isinstance(row["category"], DocumentCategory)
                    else str(row["category"]),
                    page=row["page_number"],
                    section_title=row["section_title"],
                    content=row["content"],
                    score=float(row["score"]),
                    provenance=IngestionProvenance(
                        parser_version=row["parser_version"],
                        chunking_strategy=row["chunking_strategy"],
                        embedding_model=row["embedding_model"],
                        embedding_version=row["embedding_version"],
                        pipeline_version=row["pipeline_version"],
                        status="INDEXED",
                    ),
                )
            )
        return hits

    @staticmethod
    def _filter_clause(
        category: DocumentCategory | None,
        document_type: str | None,
        access_roles: list[str] | None,
    ) -> str:
        """Build the optional WHERE fragment for metadata filters."""
        clauses: list[str] = []
        if category is not None:
            clauses.append("d.category = :category")
        if document_type:
            clauses.append("d.document_type = :document_type")
        if access_roles is not None:
            clauses.append("d.role_access @> (:role_access)::jsonb")
        return (" AND " + " AND ".join(clauses)) if clauses else ""

    @staticmethod
    def _add_filter_params(
        params: dict,
        category: DocumentCategory | None,
        document_type: str | None,
        access_roles: list[str] | None,
    ) -> None:
        """Register the bound params for the metadata filters, if present."""
        if category is not None:
            params["category"] = category.value
        if document_type:
            params["document_type"] = document_type
        if access_roles is not None:
            params["role_access"] = json.dumps(access_roles)

    async def restricted_matches(
        self,
        query: str,
        access_roles: list[str],
        *,
        limit: int = 5,
        current_only: bool = True,
    ) -> list[RestrictedDocument]:
        """Documents matching the query that the requester may NOT access.

        The probe mirrors the BM25 leg but inverts the access gate
        (``NOT (d.role_access @> :role_access::jsonb)``). It returns titles
        and the documents' allowlists only — never content — so the caller
        can reply "you cannot access this" without leaking the file's text.
        """
        sql = text(
            """
            SELECT DISTINCT d.title, d.role_access
            FROM document_chunk c
            JOIN document_version v ON v.document_version_id = c.document_version_id
            JOIN document d ON d.document_id = v.document_id
            JOIN ingestion_job j ON j.document_version_id = v.document_version_id
            WHERE j.status = 'INDEXED'
              AND v.status = 'INDEXED'
              AND d.deleted_at IS NULL
              AND c.embeddable = TRUE
              AND to_tsvector('english', c.processed_content)
                  @@ plainto_tsquery('english', :query)
              AND (:current_only = FALSE OR v.is_current = TRUE)
              AND NOT (d.role_access @> (:role_access)::jsonb)
            ORDER BY d.title
            LIMIT :limit
            """
        )
        params = {
            "query": query,
            "current_only": current_only,
            "limit": limit,
            "role_access": json.dumps(access_roles),
        }
        result = await self._session.execute(sql, params)
        return [
            RestrictedDocument(
                title=row["title"],
                allowed_roles=[str(r) for r in row["role_access"]],
            )
            for row in result.mappings()
        ]

    async def has_indexed_documents(self) -> bool:
        """True when at least one INDEXED document version is servable.

        A cheap existence probe (no ranking, no embedding) used to short-
        circuit retrieval when the knowledge base is empty — the caller can
        reply "no documents yet" without ever touching the embedder.
        """
        sql = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM document d
                JOIN document_version v ON v.document_id = d.document_id
                JOIN ingestion_job j ON j.document_version_id = v.document_version_id
                WHERE j.status = 'INDEXED'
                  AND v.status = 'INDEXED'
                  AND d.deleted_at IS NULL
            )
            """
        )
        result = await self._session.execute(sql)
        return bool(result.scalar_one())

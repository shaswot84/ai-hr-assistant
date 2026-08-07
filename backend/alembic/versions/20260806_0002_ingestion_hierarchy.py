"""Ingestion hierarchy: chunk tree columns + dedup backstop

Revision ID: 20260806_0002
Revises: 20260804_0001
Create Date: 2026-08-06

Brings ``document_chunk`` to the small-to-big hierarchical chunk tree the
ingestion contract requires (ingestion_output_contract.md §2.3):

- ``chunk_level``      -- ``document`` | ``section`` | ``leaf``
- ``parent_chunk_id``  -- FK to the enclosing node (NULL at the root)
- ``ancestors``        -- ordered parent chunk_id chain (root-most last)
- ``section_path``     -- full heading path, e.g. "A > B > C"
- ``embeddable``       -- 1 for leaf rows (embedded + BM25), 0 for context

Plus a partial unique index on ``document_version.checksum`` for INDEXED
versions: the checksum-dedup backstop ("SKIPPED_DUPLICATE") so identical
bytes are never indexed twice.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260806_0002"
down_revision: Union[str, None] = "20260804_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document_chunk", sa.Column("chunk_level", sa.String(length=20),
                                              nullable=False, server_default="leaf"))
    op.add_column("document_chunk", sa.Column("parent_chunk_id", sa.Uuid(), nullable=True))
    op.add_column("document_chunk", sa.Column("ancestors", sa.JSON(), nullable=True))
    op.add_column("document_chunk", sa.Column("section_path", sa.Text(), nullable=True))
    op.add_column("document_chunk", sa.Column("embeddable", sa.Boolean(),
                                              nullable=False, server_default=sa.text("true")))
    op.create_foreign_key(
        "fk_document_chunk_parent",
        "document_chunk", "document_chunk",
        ["parent_chunk_id"], ["chunk_id"],
    )
    op.create_index(
        "ix_document_chunk_parent", "document_chunk",
        ["document_version_id", "parent_chunk_id"],
    )

    # Dedup backstop: at most one INDEXED version per content checksum.
    op.create_index(
        "uq_version_checksum_indexed", "document_version", ["checksum"],
        unique=True, postgresql_where=sa.text("status = 'INDEXED'"),
    )


def downgrade() -> None:
    op.drop_index("uq_version_checksum_indexed", table_name="document_version")
    op.drop_index("ix_document_chunk_parent", table_name="document_chunk")
    # Tolerate both the alembic-managed FK name and the auto-generated one
    # (dev/test schemas created via Base.metadata.create_all).
    op.execute(
        "ALTER TABLE document_chunk DROP CONSTRAINT IF EXISTS fk_document_chunk_parent"
    )
    op.execute(
        "ALTER TABLE document_chunk DROP CONSTRAINT IF EXISTS "
        "document_chunk_parent_chunk_id_fkey"
    )
    op.drop_column("document_chunk", "embeddable")
    op.drop_column("document_chunk", "section_path")
    op.drop_column("document_chunk", "ancestors")
    op.drop_column("document_chunk", "parent_chunk_id")
    op.drop_column("document_chunk", "chunk_level")

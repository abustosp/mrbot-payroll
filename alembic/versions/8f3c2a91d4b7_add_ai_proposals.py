"""add ai proposals

Revision ID: 8f3c2a91d4b7
Revises: 57b478c5f289
Create Date: 2026-10-26 15:45:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '8f3c2a91d4b7'
down_revision: str | None = '57b478c5f289'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'ai_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.String(length=200), nullable=False),
        sa.Column('document_hash', sa.String(length=128), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('raw_json', sa.JSON(), nullable=False),
        sa.Column('validation_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_formula_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'rejected', 'published')",
            name=op.f('ck_ai_proposals_valid_status'),
        ),
        sa.ForeignKeyConstraint(
            ['approved_by'],
            ['users.id'],
            name=op.f('fk_ai_proposals_approved_by_users'),
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organizations.id'],
            name=op.f('fk_ai_proposals_organization_id_organizations'),
        ),
        sa.ForeignKeyConstraint(
            ['published_formula_id'],
            ['formula_definitions.id'],
            name=op.f('fk_ai_proposals_published_formula_id_formula_definitions'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_proposals')),
    )


def downgrade() -> None:
    op.drop_table('ai_proposals')

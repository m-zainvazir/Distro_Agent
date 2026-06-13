"""add_tenant_crm_config

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_crm_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("crm_type", sa.String(length=50), nullable=False),
        sa.Column("webhook_url", sa.String(length=2000), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=True),
        sa.Column("sheet_name", sa.String(length=255), nullable=True, server_default="DistroAgent"),
        sa.Column("hmac_secret", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("extra_config", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_crm_configs_tenant_id"),
    )
    op.create_index(
        op.f("ix_tenant_crm_configs_tenant_id"),
        "tenant_crm_configs",
        ["tenant_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tenant_crm_configs_tenant_id"), table_name="tenant_crm_configs"
    )
    op.drop_table("tenant_crm_configs")

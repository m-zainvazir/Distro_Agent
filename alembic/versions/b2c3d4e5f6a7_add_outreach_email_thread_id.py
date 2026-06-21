"""reconcile schema with models: outreach_emails.thread_id + drop redundant crm uq

Two model/migration drifts found while verifying migrations apply cleanly:
  1. OutreachEmail.thread_id (LangGraph checkpoint thread) existed in the model
     but no migration ever created the column.
  2. tenant_crm_configs had BOTH a unique index (ix_…, which the model produces
     via unique=True) and a redundant named UniqueConstraint (uq_…). The model
     only declares the unique index, so the named constraint is drift.

Revision ID: b2c3d4e5f6a7
Revises: a1f2b3c4d5e6
Create Date: 2026-06-19 00:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1f2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_emails",
        sa.Column("thread_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_outreach_emails_thread_id"),
        "outreach_emails",
        ["thread_id"],
        unique=False,
    )
    # Redundant with the unique index ix_tenant_crm_configs_tenant_id.
    op.drop_constraint(
        "uq_tenant_crm_configs_tenant_id", "tenant_crm_configs", type_="unique"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_tenant_crm_configs_tenant_id", "tenant_crm_configs", ["tenant_id"]
    )
    op.drop_index(
        op.f("ix_outreach_emails_thread_id"), table_name="outreach_emails"
    )
    op.drop_column("outreach_emails", "thread_id")

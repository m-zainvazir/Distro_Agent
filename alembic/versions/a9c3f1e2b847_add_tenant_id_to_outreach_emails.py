"""add_tenant_id_to_outreach_emails

Revision ID: a9c3f1e2b847
Revises: e6b3259c5c3b
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c3f1e2b847"
down_revision: Union[str, Sequence[str], None] = "e6b3259c5c3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_emails",
        sa.Column("tenant_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f("ix_outreach_emails_tenant_id"),
        "outreach_emails",
        ["tenant_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_outreach_emails_tenant_id",
        "outreach_emails",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Back-fill: set tenant_id from the parent campaign's tenant_id.
    op.execute(
        """
        UPDATE outreach_emails oe
        SET    tenant_id = oc.tenant_id
        FROM   outreach_campaigns oc
        WHERE  oe.campaign_id = oc.id
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_outreach_emails_tenant_id", "outreach_emails", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_outreach_emails_tenant_id"), table_name="outreach_emails"
    )
    op.drop_column("outreach_emails", "tenant_id")

"""make outreach_emails.tenant_id non-nullable (backfill from campaign)

Revision ID: a1f2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1f2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill any rows still missing tenant_id from their parent campaign.
    # outreach_emails.campaign_id is non-nullable and outreach_campaigns.tenant_id
    # is non-nullable, so this fully populates the column before the constraint.
    op.execute(
        """
        UPDATE outreach_emails oe
        SET    tenant_id = oc.tenant_id
        FROM   outreach_campaigns oc
        WHERE  oe.campaign_id = oc.id
          AND  oe.tenant_id IS NULL
        """
    )
    op.alter_column(
        "outreach_emails",
        "tenant_id",
        existing_type=sa.UUID(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "outreach_emails",
        "tenant_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

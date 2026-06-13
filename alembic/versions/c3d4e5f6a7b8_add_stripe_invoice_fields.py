"""add_stripe_invoice_fields

Revision ID: c3d4e5f6a7b8
Revises: f2a8c4d1e903
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "f2a8c4d1e903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_emails",
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outreach_emails",
        # Values: invoice_pending | invoice_sent | invoice_rejected | send_failed |
        #         payment_failed | overdue | deal_closed
        sa.Column("deal_status", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_emails", "deal_status")
    op.drop_column("outreach_emails", "stripe_invoice_id")

"""domain_provisioning

Revision ID: f0a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # provisioning_status tracks where the domain is in the registration flow:
    # pending | dns_configured | dns_verified | warmup | failed
    # Existing rows default to "warmup" (they are already in the warmup ramp).
    op.add_column(
        "sending_domains",
        sa.Column(
            "provisioning_status",
            sa.String(length=50),
            nullable=False,
            server_default="warmup",
        ),
    )
    op.add_column(
        "sending_domains",
        sa.Column(
            "dns_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sending_domains", "dns_verified_at")
    op.drop_column("sending_domains", "provisioning_status")

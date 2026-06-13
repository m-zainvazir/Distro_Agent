"""add_scoring_weights

Revision ID: f2a8c4d1e903
Revises: a9c3f1e2b847
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8c4d1e903"
down_revision: Union[str, Sequence[str], None] = "a9c3f1e2b847"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scoring_weights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("vertical_tag", sa.String(length=100), nullable=False),
        sa.Column("visual_weight", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("category_weight", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("price_weight", sa.Float(), nullable=False, server_default="0.20"),
        sa.Column("engagement_weight", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("wholesale_weight", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("calibrated_at", sa.DateTime(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_scoring_weights_vertical_tag"),
        "scoring_weights",
        ["vertical_tag"],
        unique=True,
    )

    op.add_column(
        "outreach_campaigns",
        sa.Column("vertical_tag", sa.String(length=100), nullable=True),
    )
    op.create_index(
        op.f("ix_outreach_campaigns_vertical_tag"),
        "outreach_campaigns",
        ["vertical_tag"],
        unique=False,
    )

    # Seed a global "all" row with the default weights so get_weights() always
    # finds a calibrated row even before the first daily run.
    op.execute(
        """
        INSERT INTO scoring_weights
            (id, vertical_tag, visual_weight, category_weight, price_weight,
             engagement_weight, wholesale_weight, sample_size)
        VALUES
            (gen_random_uuid(), 'all', 0.35, 0.25, 0.20, 0.10, 0.10, 0)
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_outreach_campaigns_vertical_tag"), table_name="outreach_campaigns"
    )
    op.drop_column("outreach_campaigns", "vertical_tag")
    op.drop_index(
        op.f("ix_scoring_weights_vertical_tag"), table_name="scoring_weights"
    )
    op.drop_table("scoring_weights")

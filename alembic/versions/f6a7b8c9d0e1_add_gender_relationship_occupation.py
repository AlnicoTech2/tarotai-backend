"""add gender, relationship_status, occupation to users

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("gender", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("relationship_status", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("occupation", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "occupation")
    op.drop_column("users", "relationship_status")
    op.drop_column("users", "gender")

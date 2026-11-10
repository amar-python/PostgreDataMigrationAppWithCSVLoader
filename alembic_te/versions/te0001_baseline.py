"""Baseline: the T&E tables as they were before versioned tenant migrations (#184).

Nothing to run. This revision names the shape every tenant had until now: the
twelve tables cloned from the template by api/tenancy.py's ``provision_te_tables``,
before #177 added ``program_id`` and the composite foreign keys. A tenant that has
T&E tables but no version table is stamped here, then upgraded to head.

Revision ID: te0001
Revises:
Create Date: 2026-11-09
"""

revision = "te0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

"""replace local identities with cloud-auth users

Revision ID: a92c0f7b2e11
Revises: 31bf0479a454
Create Date: 2026-07-23 01:00:00+00:00

This is intentionally a fresh-deployment migration. It refuses to run when
OpenPaper already contains user-owned data, because silently inventing a UUID
to BIGINT identity mapping would attach data to the wrong cloud-auth account.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a92c0f7b2e11"
down_revision: Union[str, None] = "31bf0479a454"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_COLUMNS = (
    ("zotero_oauth_pending", "user_id", "CASCADE"),
    ("zotero_connections", "user_id", "CASCADE"),
    ("zotero_imported_items", "user_id", "CASCADE"),
    ("paper_upload_jobs", "user_id", "CASCADE"),
    ("messages", "user_id", None),
    ("conversations", "user_id", None),
    ("artifacts", "user_id", "CASCADE"),
    ("paper_tags", "user_id", "CASCADE"),
    ("papers", "user_id", None),
    ("project", "admin_id", None),
    ("project_role_invitations", "invited_by", None),
    ("project_role", "user_id", None),
    ("paper_notes", "user_id", None),
    ("highlights", "user_id", None),
    ("annotations", "user_id", None),
    ("audio_overview_jobs", "user_id", "CASCADE"),
    ("audio_overviews", "user_id", "CASCADE"),
    ("subscriptions", "user_id", "CASCADE"),
    ("onboarding", "user_id", "CASCADE"),
    ("discover_searches", "user_id", "CASCADE"),
    ("data_table_extraction_jobs", "user_id", "CASCADE"),
    ("referral_codes", "user_id", "CASCADE"),
    ("referrals", "referrer_user_id", "CASCADE"),
    ("referrals", "referee_user_id", "CASCADE"),
)


def _drop_column_foreign_keys(table: str, column: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for foreign_key in inspector.get_foreign_keys(table):
        if column in foreign_key["constrained_columns"]:
            op.drop_constraint(foreign_key["name"], table, type_="foreignkey")


def _assert_fresh_openpaper_database() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT to_regclass('auth.users')")).scalar() is None:
        raise RuntimeError(
            "cloud-auth migrations must run before OpenPaper migrations: "
            "auth.users does not exist"
        )

    tables = sorted({table for table, _column, _ondelete in USER_COLUMNS} | {"users"})
    for table in tables:
        has_rows = bind.execute(
            sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" LIMIT 1)')
        ).scalar()
        if has_rows:
            raise RuntimeError(
                f"cannot replace local identities: {table} contains data; "
                "perform an explicit identity-mapping migration first"
            )


def upgrade() -> None:
    _assert_fresh_openpaper_database()

    op.drop_constraint(
        "check_referral_no_self_referral", "referrals", type_="check"
    )
    for table, column, ondelete in USER_COLUMNS:
        _drop_column_foreign_keys(table, column)
        op.alter_column(
            table,
            column,
            existing_type=postgresql.UUID(),
            type_=sa.BigInteger(),
            postgresql_using="NULL::bigint",
        )
        op.create_foreign_key(
            f"fk_{table}_{column}_auth_users",
            table,
            "users",
            [column],
            ["id"],
            referent_schema="auth",
            ondelete=ondelete,
        )
    op.create_check_constraint(
        "check_referral_no_self_referral",
        "referrals",
        "referrer_user_id <> referee_user_id",
    )

    op.drop_table("sessions")
    op.drop_table("users")
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("locale", sa.String(), nullable=True),
        sa.Column(
            "is_admin", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "is_blocked", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("referral_toast_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["auth.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in sorted({table for table, _column, _ondelete in USER_COLUMNS}):
        has_rows = bind.execute(
            sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" LIMIT 1)')
        ).scalar()
        if has_rows:
            raise RuntimeError(
                f"cannot restore UUID identities: {table} contains cloud-auth data"
            )

    op.drop_table("user_profiles")
    op.drop_constraint(
        "check_referral_no_self_referral", "referrals", type_="check"
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("picture", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("auth_provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), nullable=True),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False),
        sa.Column("email_verification_token", sa.String(), nullable=True),
        sa.Column(
            "email_verification_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("referral_toast_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index(
        "ix_users_provider_user_id", "users", ["provider_user_id"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_token", "sessions", ["token"], unique=True)

    for table, column, ondelete in USER_COLUMNS:
        op.drop_constraint(
            f"fk_{table}_{column}_auth_users", table, type_="foreignkey"
        )
        op.alter_column(
            table,
            column,
            existing_type=sa.BigInteger(),
            type_=postgresql.UUID(),
            postgresql_using="NULL::uuid",
        )
        op.create_foreign_key(
            f"fk_{table}_{column}_users",
            table,
            "users",
            [column],
            ["id"],
            ondelete=ondelete,
        )
    op.create_check_constraint(
        "check_referral_no_self_referral",
        "referrals",
        "referrer_user_id <> referee_user_id",
    )

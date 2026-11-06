"""Members, private tracks, idempotent events and forced RLS.

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("tracks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(200)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artist", sa.String(300), nullable=False),
        sa.Column("album", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "source_key", name="uq_tracks_user_source"),
        sa.UniqueConstraint("user_id", "id", name="uq_tracks_user_id"))
    op.create_index("ix_tracks_user_title", "tracks", ["user_id", "title"])
    op.create_table("listen_events",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("listened_ms", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "track_id"], ["tracks.user_id", "tracks.id"], ondelete="CASCADE"),
        sa.CheckConstraint("listened_ms >= 30000 AND listened_ms <= 86400000", name="ck_listen_duration"))
    op.create_index("ix_events_user_track_observed", "listen_events", ["user_id", "track_id", "observed_at"])
    # Roles are provisioned separately and are never owners of these tables.
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO firstlisten_app, firstlisten_reader")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON members, auth_sessions, tracks, listen_events TO firstlisten_app")
    op.execute("GRANT SELECT ON tracks, listen_events TO firstlisten_reader")
    for table in ("tracks", "listen_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY own_rows ON {table}
            TO firstlisten_app, firstlisten_reader
            USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
            WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)""")


def downgrade():
    for table in ("listen_events", "tracks", "auth_sessions", "members"):
        op.drop_table(table)


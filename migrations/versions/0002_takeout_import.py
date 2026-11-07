"""Takeout imports, nullable unknown durations, provenance and forced RLS."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("tracks", "artist", existing_type=sa.String(300), nullable=True)
    op.drop_constraint("ck_listen_duration", "listen_events", type_="check")
    op.alter_column("listen_events", "listened_ms", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("listen_events", sa.Column("source", sa.String(40), nullable=False, server_default="android_media_session"))
    op.add_column("listen_events", sa.Column("source_event_key", sa.String(64)))
    op.add_column("listen_events", sa.Column("occurrence_no", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_listen_source_duration", "listen_events",
        "(source = 'android_media_session' AND listened_ms IS NOT NULL AND listened_ms >= 30000 AND listened_ms <= 86400000) OR (source = 'google_takeout_my_activity' AND listened_ms IS NULL AND source_event_key IS NOT NULL)")
    op.create_check_constraint("ck_listen_occurrence", "listen_events", "occurrence_no >= 1")
    op.create_unique_constraint("uq_events_source_occurrence", "listen_events", ["user_id", "source", "source_event_key", "occurrence_no"])
    op.create_table("import_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("json_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON()), sa.Column("error_code", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "id", name="uq_import_jobs_user_id"),
        sa.CheckConstraint("status IN ('processing','completed','failed')", name="ck_import_job_status"))
    op.create_index("ix_import_jobs_user_created", "import_jobs", ["user_id", "created_at"])
    op.create_table("import_evidence",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("source_index", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("raw_record", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "job_id"], ["import_jobs.user_id", "import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "event_id"], ["listen_events.user_id", "listen_events.event_id"], ondelete="CASCADE"),
        sa.CheckConstraint("source_index >= 0", name="ck_import_evidence_index"))
    op.create_table("import_issues",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("source_index", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("raw_record", sa.JSON()),
        sa.ForeignKeyConstraint(["user_id", "job_id"], ["import_jobs.user_id", "import_jobs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('review','error')", name="ck_import_issue_status"),
        sa.CheckConstraint("source_index >= 0", name="ck_import_issue_index"))
    for table in ("import_jobs", "import_evidence", "import_issues"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO firstlisten_app")
        op.execute(f"GRANT SELECT ON {table} TO firstlisten_reader")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY own_rows ON {table} TO firstlisten_app, firstlisten_reader
            USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
            WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)""")


def downgrade():
    # An automatic downgrade would discard imported history. Fail explicitly.
    raise RuntimeError("0002 downgrade requires an explicit data-preserving export/cleanup plan")

"""On PostgreSQL, refuse UPDATE and DELETE on the audit table at the database level.

The application already blocks changes (see ``AuditEvent``), but a trigger also stops a mistaken
or malicious SQL statement from rewriting history. Other databases only get the application
guard. Note: TRUNCATE is not a row operation and is not blocked; keep the application's database
account from owning the table in production if that matters to you.
"""
from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION audit_auditevent_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditevent is append-only';
END;
$$ LANGUAGE plpgsql
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS audit_auditevent_append_only ON audit_auditevent"

CREATE_TRIGGER = """
CREATE TRIGGER audit_auditevent_append_only
BEFORE UPDATE OR DELETE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION audit_auditevent_block_change()
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS audit_auditevent_block_change()"


def add_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for statement in (FUNCTION, DROP_TRIGGER, CREATE_TRIGGER):
        schema_editor.execute(statement, params=None)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for statement in (DROP_TRIGGER, DROP_FUNCTION):
        schema_editor.execute(statement, params=None)


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunPython(add_trigger, remove_trigger)]

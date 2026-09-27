from django.db import migrations


def protect(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute("""
            CREATE TRIGGER support_immutable_update BEFORE UPDATE ON accounts_user
            WHEN OLD.support = 1 AND (NEW.support != 1 OR NEW.username != OLD.username
              OR NEW.role != OLD.role OR NEW.approved != 1 OR NEW.is_active != 1
              OR NEW.password != OLD.password OR NEW.must_change_password != 0)
            BEGIN SELECT RAISE(ABORT, 'Protected support account'); END;
        """)
        schema_editor.execute("""
            CREATE TRIGGER support_immutable_delete BEFORE DELETE ON accounts_user
            WHEN OLD.support = 1
            BEGIN SELECT RAISE(ABORT, 'Protected support account'); END;
        """)
    elif vendor == "postgresql":
        schema_editor.execute("""
            CREATE FUNCTION protect_support_account() RETURNS trigger AS $$
            BEGIN
              IF OLD.support THEN
                IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Protected support account'; END IF;
                IF NOT NEW.support OR NEW.username IS DISTINCT FROM OLD.username
                  OR NEW.role IS DISTINCT FROM OLD.role OR NOT NEW.approved OR NOT NEW.is_active
                  OR NEW.password IS DISTINCT FROM OLD.password OR NEW.must_change_password THEN
                  RAISE EXCEPTION 'Protected support account';
                END IF;
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql;
        """)
        schema_editor.execute(
            "CREATE TRIGGER support_immutable BEFORE UPDATE OR DELETE ON accounts_user FOR EACH ROW EXECUTE FUNCTION protect_support_account()"
        )


def unprotect(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS support_immutable_update")
        schema_editor.execute("DROP TRIGGER IF EXISTS support_immutable_delete")
    elif schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS support_immutable ON accounts_user")
        schema_editor.execute("DROP FUNCTION IF EXISTS protect_support_account()")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(protect, unprotect)]

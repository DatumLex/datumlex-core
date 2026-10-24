from django.db import migrations

TABLES = [f'warehouse_nlp{name}' for name in (
    'document', 'textversion', 'sourceobservation', 'extraction', 'evidence', 'revision', 'snapshot',
)]


def install(apps, editor):
    if editor.connection.vendor == 'postgresql':
        editor.execute("""
            CREATE FUNCTION nlp_deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'NLP history is append-only'; END; $$;
        """)
        for table in TABLES:
            editor.execute(f'CREATE TRIGGER nlp_no_change BEFORE UPDATE OR DELETE ON {table} '
                           'FOR EACH ROW EXECUTE FUNCTION nlp_deny_mutation()')
            editor.execute(f'CREATE TRIGGER nlp_no_truncate BEFORE TRUNCATE ON {table} '
                           'FOR EACH STATEMENT EXECUTE FUNCTION nlp_deny_mutation()')
        editor.execute("""
            CREATE FUNCTION nlp_check_revision() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE prior warehouse_nlprevision%%ROWTYPE;
                    baseline jsonb; prior_state text; expected integer;
                    source_text text; segment jsonb; s integer; e integer;
                    previous_end integer := 0; key_name text;
            BEGIN
                SELECT original INTO baseline FROM warehouse_nlpevidence
                    WHERE id = NEW.evidence_id FOR UPDATE;
                IF baseline IS NULL THEN RAISE EXCEPTION 'Missing evidence'; END IF;
                SELECT * INTO prior FROM warehouse_nlprevision
                    WHERE evidence_id = NEW.evidence_id ORDER BY number DESC LIMIT 1;
                expected := COALESCE(prior.number, 0) + 1;
                prior_state := COALESCE(prior.state, 'pending');
                baseline := COALESCE(prior.after, baseline);
                IF NEW.number <> expected OR NEW.before <> baseline OR length(btrim(NEW.reason)) = 0 THEN
                    RAISE EXCEPTION 'Invalid revision chain';
                END IF;
                IF (prior_state = 'rejected' AND NEW.action <> 'reopen')
                   OR (prior_state = 'pending' AND NEW.action = 'reopen') THEN
                    RAISE EXCEPTION 'Invalid revision transition';
                END IF;
                IF NEW.state <> (CASE NEW.action WHEN 'approve' THEN 'approved'
                    WHEN 'correct' THEN 'corrected' WHEN 'reject' THEN 'rejected'
                    WHEN 'reopen' THEN 'pending' ELSE '' END) THEN
                    RAISE EXCEPTION 'Invalid review state';
                END IF;
                IF (NEW.action <> 'correct' AND NEW.after <> baseline)
                   OR (NEW.action = 'correct' AND NEW.after = baseline) THEN
                    RAISE EXCEPTION 'Invalid correction payload';
                END IF;
                FOREACH key_name IN ARRAY ARRAY['id','method','confidence','label_status','review_status'] LOOP
                    IF NEW.after->key_name IS DISTINCT FROM baseline->key_name THEN
                        RAISE EXCEPTION 'Immutable annotation field';
                    END IF;
                END LOOP;
                SELECT t.text INTO source_text FROM warehouse_nlptextversion t
                    JOIN warehouse_nlpextraction r ON r.text_version_id = t.id
                    JOIN warehouse_nlpevidence a ON a.extraction_id = r.id WHERE a.id = NEW.evidence_id;
                IF jsonb_typeof(NEW.after->'segments') IS DISTINCT FROM 'array'
                   OR jsonb_array_length(NEW.after->'segments') = 0 THEN
                    RAISE EXCEPTION 'Missing segments';
                END IF;
                FOR segment IN SELECT * FROM jsonb_array_elements(NEW.after->'segments') LOOP
                    IF (segment->>'start') IS NULL OR (segment->>'end') IS NULL
                       OR (segment->>'start') !~ '^[0-9]+$' OR (segment->>'end') !~ '^[0-9]+$' THEN
                        RAISE EXCEPTION 'Invalid offsets';
                    END IF;
                    s := (segment->>'start')::integer; e := (segment->>'end')::integer;
                    IF s < previous_end OR e <= s OR e > length(source_text)
                       OR substring(source_text FROM s+1 FOR e-s) IS DISTINCT FROM segment->>'text' THEN
                        RAISE EXCEPTION 'Invalid evidence span';
                    END IF;
                    previous_end := e;
                END LOOP;
                RETURN NEW;
            END; $$;
            CREATE TRIGGER nlp_revision_chain BEFORE INSERT ON warehouse_nlprevision
                FOR EACH ROW EXECUTE FUNCTION nlp_check_revision();
        """)
    elif editor.connection.vendor == 'sqlite':
        for table in TABLES:
            for action in ('UPDATE', 'DELETE'):
                editor.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                               "BEGIN SELECT RAISE(ABORT, 'NLP history is append-only'); END")


def uninstall(apps, editor):
    if editor.connection.vendor == 'postgresql':
        editor.execute('DROP TRIGGER nlp_revision_chain ON warehouse_nlprevision')
        editor.execute('DROP FUNCTION nlp_check_revision()')
        for table in TABLES:
            editor.execute(f'DROP TRIGGER nlp_no_change ON {table}')
            editor.execute(f'DROP TRIGGER nlp_no_truncate ON {table}')
        editor.execute('DROP FUNCTION nlp_deny_mutation()')
    elif editor.connection.vendor == 'sqlite':
        for table in TABLES:
            for action in ('update', 'delete'):
                editor.execute(f'DROP TRIGGER {table}_{action}')


class Migration(migrations.Migration):
    dependencies = [('warehouse', '0010_nlp_evidence_history')]
    operations = [migrations.RunPython(install, uninstall)]

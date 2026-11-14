"""Trusted one-time maintenance: separate runtime DML from database administration.

Run through azure-private-exec using the current database administrator connection.
Inject TRELLIS_RUNTIME_DB_PASSWORD securely; never commit it or pass it on a CLI.
Future schema migrations must run with the separate administrator credential.
"""
import os
import django
import psycopg
from psycopg import sql

django.setup()
from django.conf import settings
from django.db import connection

password=os.environ['TRELLIS_RUNTIME_DB_PASSWORD']
assert len(password)>=40
role='trellis_runtime'
with connection.cursor() as cursor:
    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',[role])
    if not cursor.fetchone():
        cursor.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    cursor.execute(sql.SQL('ALTER ROLE {} PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 16').format(sql.Identifier(role),sql.Literal(password)))
    cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(connection.settings_dict['NAME']),sql.Identifier(role)))
    cursor.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
    cursor.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
    cursor.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
    cursor.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}').format(sql.Identifier(role)))
    cursor.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}').format(sql.Identifier(role)))
config=settings.DATABASES['default']
with psycopg.connect(host=config['HOST'],dbname=config['NAME'],user=role,password=password,
                     sslmode='verify-full',sslrootcert='/etc/ssl/certs/ca-certificates.crt') as runtime:
    with runtime.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM auth_user');assert cursor.fetchone()[0]>0
        cursor.execute('SELECT count(*) FROM core_loginthrottle')
        cursor.execute("SELECT rolcreaterole,rolcreatedb,rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone()==(False,False,False)
        cursor.execute("SELECT has_schema_privilege(current_user,'public','CREATE')")
        assert cursor.fetchone()==(False,)
        cursor.execute('UPDATE core_loginthrottle SET attempts=attempts WHERE false')
print('Runtime role verified: TLS hostname/certificate validation, data access, no schema creation or role/database administration.')

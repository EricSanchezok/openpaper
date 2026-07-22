\set ON_ERROR_STOP on

-- Run as the RDS database owner before the first migration and again after it.
-- Required psql variables: app_role and migrator_role (existing login roles).

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'migrator_role') \gexec
SELECT format('GRANT CREATE ON DATABASE %I TO %I', current_database(), :'migrator_role') \gexec

SELECT format('CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION %I', :'migrator_role') \gexec
SELECT format('ALTER SCHEMA auth OWNER TO %I', :'migrator_role') \gexec
SELECT format('CREATE SCHEMA IF NOT EXISTS openpaper AUTHORIZATION %I', :'migrator_role') \gexec
SELECT format('ALTER SCHEMA openpaper OWNER TO %I', :'migrator_role') \gexec

REVOKE CREATE ON SCHEMA auth FROM PUBLIC;
REVOKE CREATE ON SCHEMA openpaper FROM PUBLIC;
GRANT USAGE ON SCHEMA auth, openpaper, public TO :"app_role";
GRANT USAGE, CREATE ON SCHEMA auth, openpaper TO :"migrator_role";
GRANT USAGE, CREATE ON SCHEMA public TO :"migrator_role";

SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO %I',
  schemaname,
  tablename,
  :'app_role'
)
FROM pg_tables
WHERE schemaname IN ('auth', 'openpaper')
ORDER BY schemaname, tablename \gexec

SELECT format(
  'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',
  sequence_schema,
  sequence_name,
  :'app_role'
)
FROM information_schema.sequences
WHERE sequence_schema IN ('auth', 'openpaper')
ORDER BY sequence_schema, sequence_name \gexec

SELECT format('GRANT USAGE ON TYPE %I TO %I', type_name, :'app_role')
FROM (VALUES ('account_status'), ('operation_type')) AS known_types(type_name)
WHERE to_regtype(type_name) IS NOT NULL
ORDER BY type_name \gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA auth '
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'migrator_role',
  :'app_role'
) \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA auth '
  'GRANT USAGE, SELECT ON SEQUENCES TO %I',
  :'migrator_role',
  :'app_role'
) \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA openpaper '
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'migrator_role',
  :'app_role'
) \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA openpaper '
  'GRANT USAGE, SELECT ON SEQUENCES TO %I',
  :'migrator_role',
  :'app_role'
) \gexec

SELECT format('REVOKE ALL ON TABLE openpaper.alembic_version FROM %I', :'app_role')
WHERE to_regclass('openpaper.alembic_version') IS NOT NULL \gexec
SELECT format('REVOKE ALL ON TABLE public._cloud_auth_migrations FROM %I', :'app_role')
WHERE to_regclass('public._cloud_auth_migrations') IS NOT NULL \gexec

REVOKE CREATE ON SCHEMA auth, openpaper, public FROM :"app_role";
SELECT format('REVOKE CREATE ON DATABASE %I FROM %I', current_database(), :'app_role') \gexec

\set ON_ERROR_STOP on

-- SanchezCloud database privilege bootstrap for Scholens.
-- Required existing LOGIN roles:
--   auth_migrator_role       owns only auth.*
--   product_migrator_role    owns only scholens.*
--   app_role                 runs the Scholens API
--
-- Run as the database owner before cloud-auth migration, after cloud-auth
-- migration, and after Scholens migration. Re-running is safe.

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role') \gexec
SELECT format(
  'GRANT CONNECT ON DATABASE %I TO %I',
  current_database(),
  :'auth_migrator_role'
) \gexec
SELECT format(
  'GRANT CONNECT ON DATABASE %I TO %I',
  current_database(),
  :'product_migrator_role'
) \gexec

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM :"app_role";
REVOKE ALL ON SCHEMA public FROM :"auth_migrator_role";
REVOKE ALL ON SCHEMA public FROM :"product_migrator_role";

SELECT format(
  'CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION %I',
  :'auth_migrator_role'
) \gexec
SELECT format('ALTER SCHEMA auth OWNER TO %I', :'auth_migrator_role') \gexec
SELECT format(
  'CREATE SCHEMA IF NOT EXISTS scholens AUTHORIZATION %I',
  :'product_migrator_role'
) \gexec
SELECT format('ALTER SCHEMA scholens OWNER TO %I', :'product_migrator_role') \gexec

REVOKE CREATE ON SCHEMA auth FROM PUBLIC;
REVOKE CREATE ON SCHEMA scholens FROM PUBLIC;
GRANT USAGE ON SCHEMA auth TO :"app_role", :"product_migrator_role";
GRANT USAGE ON SCHEMA scholens TO :"app_role";
GRANT USAGE, CREATE ON SCHEMA auth TO :"auth_migrator_role";
GRANT USAGE, CREATE ON SCHEMA scholens TO :"product_migrator_role";

-- These grants become available after the independent cloud-auth baseline.
SELECT format(
  'GRANT SELECT, INSERT, UPDATE ON TABLE auth.users, '
  'auth.refresh_tokens TO %I',
  :'app_role'
)
WHERE to_regclass('auth.users') IS NOT NULL
  AND to_regclass('auth.refresh_tokens') IS NOT NULL \gexec
SELECT format(
  'GRANT SELECT ON TABLE auth.schema_migrations TO %I',
  :'product_migrator_role'
)
WHERE to_regclass('auth.schema_migrations') IS NOT NULL \gexec
SELECT format(
  'GRANT REFERENCES ON TABLE auth.users TO %I',
  :'product_migrator_role'
)
WHERE to_regclass('auth.users') IS NOT NULL \gexec

SELECT format(
  'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',
  sequence_schema,
  sequence_name,
  :'app_role'
)
FROM information_schema.sequences
WHERE sequence_schema = 'auth'
  AND sequence_name IN ('users_id_seq', 'refresh_tokens_id_seq')
ORDER BY sequence_name \gexec

-- These grants become available after the Scholens baseline.
SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO %I',
  schemaname,
  tablename,
  :'app_role'
)
FROM pg_tables
WHERE schemaname = 'scholens'
  AND tablename <> 'schema_migrations'
ORDER BY tablename \gexec

-- Product code may append attribution, but cannot mutate or erase it.
SELECT format(
  'REVOKE UPDATE, DELETE ON TABLE scholens.operation_journal_entries FROM %I',
  :'app_role'
)
WHERE to_regclass('scholens.operation_journal_entries') IS NOT NULL \gexec

SELECT format(
  'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',
  sequence_schema,
  sequence_name,
  :'app_role'
)
FROM information_schema.sequences
WHERE sequence_schema = 'scholens'
ORDER BY sequence_name \gexec

ALTER DEFAULT PRIVILEGES FOR ROLE :"product_migrator_role" IN SCHEMA scholens
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"product_migrator_role" IN SCHEMA scholens
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_role";

SELECT format(
  'REVOKE ALL ON TABLE auth.schema_migrations FROM %I',
  :'app_role'
)
WHERE to_regclass('auth.schema_migrations') IS NOT NULL \gexec
SELECT format(
  'REVOKE ALL ON TABLE scholens.schema_migrations FROM %I',
  :'app_role'
)
WHERE to_regclass('scholens.schema_migrations') IS NOT NULL \gexec

REVOKE CREATE ON SCHEMA auth FROM :"app_role", :"product_migrator_role";
REVOKE CREATE ON SCHEMA scholens FROM :"app_role", :"auth_migrator_role";
SELECT format('REVOKE CREATE ON DATABASE %I FROM %I', current_database(), :'app_role') \gexec
SELECT format(
  'REVOKE CREATE ON DATABASE %I FROM %I',
  current_database(),
  :'auth_migrator_role'
) \gexec
SELECT format(
  'REVOKE CREATE ON DATABASE %I FROM %I',
  current_database(),
  :'product_migrator_role'
) \gexec

-- Run as the postgres superuser:  sudo -u postgres psql -v ON_ERROR_STOP=1 -f roles.sql
-- Idempotent. Two roles on the hextrack_v2 database:
--   hextrack_v2   existing owner of the schema; used only by hextrack-migrate.service (DDL).
--   hextrack_app  new login role for the api/worker/bot: read and write rows, nothing else
--                 (no DDL, no ownership, can't create roles, databases or schemas).
-- Both authenticate by Unix-socket peer auth (pg_ident map "hextrack"), so no password is stored.

SELECT 'CREATE ROLE hextrack_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hextrack_app') \gexec
ALTER ROLE hextrack_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 40;

-- Only these roles may connect to the database at all.
REVOKE CONNECT, TEMPORARY ON DATABASE hextrack_v2 FROM PUBLIC;
GRANT CONNECT ON DATABASE hextrack_v2 TO hextrack_v2, hextrack_app;

\connect hextrack_v2
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO hextrack_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hextrack_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO hextrack_app;
-- Tables and sequences that future migrations create (as hextrack_v2) get the same grants.
ALTER DEFAULT PRIVILEGES FOR ROLE hextrack_v2 IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hextrack_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hextrack_v2 IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO hextrack_app;
-- alembic_version is the migrator's business.
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM hextrack_app;

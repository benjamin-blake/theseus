-- Scoped catalog login for the DuckLake telemetry writer (Decision 213 cl.3, PLAN-url-only-invoke-guard).
--
-- WHAT THIS IS: every catalog-connecting Lambda used to share the ducklake_ops owner login, which the
-- Neon API creates as a member of neon_superuser and which reaches both catalogs' metadata. The telemetry
-- writer instead connects as its own SQL-created role: LOGIN only, DML-only on the smoke catalog's
-- metadata schema, a connection limit, and nothing on the production metadata schema, public, or the
-- database itself. A Postgres role created by SQL is not a neon_superuser member.
--
-- HOW IT IS APPLIED: by the ducklake_maintenance verb provision_telemetry_login, run as the ducklake_ops
-- owner login against the ducklake_ops database, on Neon now and on RDS after the swap's restore. No
-- CC-web container has TCP/5432 egress, so the verb runs this file inside the Lambda (it lives beside the
-- verb so that an edit to it triggers the governed deploy and the drift sensor like any maintenance
-- source). The verb reads this file with no query parameters, so a percent sign in a comment stays literal.
-- It is idempotent: every statement is a no-op on re-run, and a re-run is how rotation and the RDS swap
-- re-apply it. The role's password is not set here; the verb sets it from the role's secret afterwards,
-- so this file stays password-free; until that step the role has no password and cannot log in.
--
-- LIMITS: REPLICATION and BYPASSRLS stay at their NO defaults and are not named, since a non-superuser
-- owner may not set them. CONNECTION LIMIT 10 is twice the telemetry writer's reserved concurrency of 5,
-- pending the per-container session measurement in the telemetry plan. Schema migrations stay an admin
-- step under the owner login (Decision 213 cl.3).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ducklake_telemetry_writer') THEN
        CREATE ROLE ducklake_telemetry_writer NOLOGIN;
    END IF;
END
$$;

ALTER ROLE ducklake_telemetry_writer LOGIN NOINHERIT NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10;
ALTER ROLE ducklake_telemetry_writer SET statement_timeout = '60s';

GRANT CONNECT ON DATABASE ducklake_ops TO ducklake_telemetry_writer;
GRANT USAGE ON SCHEMA ducklake_smoke TO ducklake_telemetry_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ducklake_smoke TO ducklake_telemetry_writer;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA ducklake_smoke TO ducklake_telemetry_writer;

-- Objects the owner login creates later in the smoke schema (new DuckLake metadata tables) stay reachable.
ALTER DEFAULT PRIVILEGES FOR ROLE ducklake_ops IN SCHEMA ducklake_smoke
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ducklake_telemetry_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE ducklake_ops IN SCHEMA ducklake_smoke
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ducklake_telemetry_writer;

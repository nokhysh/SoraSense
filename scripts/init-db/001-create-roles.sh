#!/bin/sh
# SoraSenseで使用するPostgreSQLロールを冪等に作成する。

set -eu

: "${POSTGRES_DB:?POSTGRES_DB must be set}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${SORASENSE_MIGRATOR_PASSWORD:?SORASENSE_MIGRATOR_PASSWORD must be set}"
: "${SORASENSE_APP_PASSWORD:?SORASENSE_APP_PASSWORD must be set}"
: "${GRAFANA_READER_PASSWORD:?GRAFANA_READER_PASSWORD must be set}"

psql \
    --set=ON_ERROR_STOP=1 \
    --set=migrator_password="${SORASENSE_MIGRATOR_PASSWORD}" \
    --set=app_password="${SORASENSE_APP_PASSWORD}" \
    --set=grafana_password="${GRAFANA_READER_PASSWORD}" \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" <<'SQL'
SELECT format(
    'CREATE ROLE sorasense_migrator LOGIN PASSWORD %L',
    :'migrator_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'sorasense_migrator'
) \gexec

SELECT format(
    'CREATE ROLE sorasense_app LOGIN PASSWORD %L',
    :'app_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'sorasense_app'
) \gexec

SELECT format(
    'CREATE ROLE grafana_reader LOGIN PASSWORD %L',
    :'grafana_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader'
) \gexec

ALTER ROLE sorasense_migrator WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'migrator_password';
ALTER ROLE sorasense_app WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'app_password';
ALTER ROLE grafana_reader WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'grafana_password';

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format(
    'GRANT CONNECT, CREATE ON DATABASE %I TO sorasense_migrator',
    current_database()
) \gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO sorasense_app, grafana_reader',
    current_database()
) \gexec

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO sorasense_migrator;
SQL

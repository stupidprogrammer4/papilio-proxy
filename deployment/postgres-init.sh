#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password PAPILIO_DB_PASSWORD
SELECT format('CREATE ROLE papilio LOGIN PASSWORD %L', :'app_password') \gexec
ALTER SCHEMA public OWNER TO papilio;
GRANT CONNECT, TEMPORARY ON DATABASE papilio TO papilio;
SQL

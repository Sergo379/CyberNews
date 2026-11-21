#!/usr/bin/env bash

# The official image can source this file. Keep shell options local to this script.
(
    set -eu
    export PGCLIENTENCODING=UTF8

    for password_name in AUTH_DB_PASSWORD COLLECTOR_DB_PASSWORD ARTICLE_DB_PASSWORD \
        COMMUNITY_DB_PASSWORD MODERATION_DB_PASSWORD NOTIFICATION_DB_PASSWORD; do
        if [ -z "${!password_name}" ]; then
            printf 'Missing PostgreSQL initialization variable: %s\n' "$password_name" >&2
            exit 1
        fi
    done

    psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
REVOKE ALL ON DATABASE postgres, template0, template1 FROM PUBLIC;
SQL

    create_database() {
        export CYBERNEWS_INIT_ROLE="$1"
        export CYBERNEWS_INIT_DB="$2"
        export CYBERNEWS_INIT_PASSWORD="${!3}"
        psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
\getenv role CYBERNEWS_INIT_ROLE
\getenv database CYBERNEWS_INIT_DB
\getenv password CYBERNEWS_INIT_PASSWORD
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L', :'role', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', :'database', :'role', 'UTF8') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'database') \gexec
SQL
        unset CYBERNEWS_INIT_PASSWORD
    }

    create_database auth_svc auth_db AUTH_DB_PASSWORD
    create_database collector_svc collector_db COLLECTOR_DB_PASSWORD
    create_database article_svc article_db ARTICLE_DB_PASSWORD
    create_database community_svc community_db COMMUNITY_DB_PASSWORD
    create_database moderation_svc moderation_db MODERATION_DB_PASSWORD
    create_database notification_svc notification_db NOTIFICATION_DB_PASSWORD
)

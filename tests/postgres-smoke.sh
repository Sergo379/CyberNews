#!/usr/bin/env bash
set -euo pipefail

phase=$1
marker=$2
[[ $marker =~ ^smoke_[a-f0-9]{32}$ ]] || exit 2
export PGHOST=127.0.0.1 PGPORT=5432 PGCONNECT_TIMEOUT=3

query() {
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align --quiet "$@"
}

check_database() {
    local user=$1 database=$2 password_key=$3 result
    export PGPASSWORD="${!password_key}"
    result=$(query --username "$user" --dbname "$database" --command \
        "SELECT current_user, current_database(), current_setting('server_encoding'),
            (SELECT string_agg(datname::text, ',' ORDER BY datname)
             FROM pg_database WHERE has_database_privilege(current_user, oid, 'CONNECT')),
            (SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication)
             FROM pg_roles WHERE rolname = current_user);")
    if [[ $result != "$user|$database|UTF8|$database|t" ]]; then
        printf 'Unexpected PostgreSQL identity or permissions for %s\n' "$user" >&2
        return 1
    fi

    if query --username "$user" --dbname postgres --command 'SELECT 1' >/dev/null 2>&1; then
        printf 'PostgreSQL shared database accepted %s\n' "$user" >&2
        return 1
    fi
    printf '%s -> %s (UTF-8, isolated)\n' "$user" "$database"
}

if [[ $phase == isolation ]]; then
    check_database auth_svc auth_db AUTH_DB_PASSWORD
    check_database collector_svc collector_db COLLECTOR_DB_PASSWORD
    check_database article_svc article_db ARTICLE_DB_PASSWORD
    check_database community_svc community_db COMMUNITY_DB_PASSWORD
    check_database moderation_svc moderation_db MODERATION_DB_PASSWORD
    check_database notification_svc notification_db NOTIFICATION_DB_PASSWORD
    exit 0
fi

export PGUSER=auth_svc PGDATABASE=auth_db PGPASSWORD="$AUTH_DB_PASSWORD"
case "$phase" in
    write)
        query --command "CREATE TABLE public.$marker (value text NOT NULL);
                         INSERT INTO public.$marker VALUES ('$marker');"
        ;;
    read)
        [[ $(query --command "SELECT value FROM public.$marker;") == "$marker" ]]
        ;;
    cleanup)
        query --command "DROP TABLE IF EXISTS public.$marker;"
        ;;
    *)
        exit 2
        ;;
esac

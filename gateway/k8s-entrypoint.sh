#!/bin/sh
set -eu

# Nginx's asynchronous resolver does not apply the Pod's DNS search suffix.
KUBE_DNS_RESOLVERS=$(awk '/^nameserver[[:space:]]/ {
    if ($2 ~ /:/) printf "[%s] ", $2; else printf "%s ", $2
}' /etc/resolv.conf)
service_domain=$(awk '/^search[[:space:]]/ {
    for (i=2; i<=NF; i++) if ($i ~ /^svc\./) {print $i; exit}
}' /etc/resolv.conf)
test -n "$KUBE_DNS_RESOLVERS"
test -n "$service_domain"
test -n "$POD_NAMESPACE"
suffix="$POD_NAMESPACE.$service_domain:${BACKEND_PORT:-8000}"

export KUBE_DNS_RESOLVERS
export AUTH_UPSTREAM="auth.$suffix" COLLECTOR_UPSTREAM="collector.$suffix"
export ARTICLES_UPSTREAM="articles.$suffix" COMMUNITY_UPSTREAM="community.$suffix"
export MODERATION_UPSTREAM="moderation.$suffix" NOTIFICATIONS_UPSTREAM="notifications.$suffix"

allowed='$KUBE_DNS_RESOLVERS $AUTH_UPSTREAM $COLLECTOR_UPSTREAM $ARTICLES_UPSTREAM $COMMUNITY_UPSTREAM $MODERATION_UPSTREAM $NOTIFICATIONS_UPSTREAM'
envsubst "$allowed" < /etc/nginx/templates/cybernews.conf > /tmp/cybernews.conf
exec "$@"

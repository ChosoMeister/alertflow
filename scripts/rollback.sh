#!/bin/sh
set -eu

if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
    printf '%s\n' "Usage: scripts/rollback.sh /explicit/backup/directory" >&2
    exit 2
fi

project_dir=${ALERTFLOW_PROJECT_DIR:-/docker/alertflow}
backup_dir=$1
test -f "$backup_dir/docker-compose.yml"
cp "$backup_dir/docker-compose.yml" "$project_dir/docker-compose.yml"
if [ -f "$backup_dir/release.env" ]; then
    set -a
    . "$backup_dir/release.env"
    set +a
    export ALERTFLOW_RELEASE ALERTFLOW_GIT_COMMIT
fi
cd "$project_dir"
if [ -f "$backup_dir/images.txt" ]; then
    while read -r service image_id; do
        [ -n "$service" ] || continue
        docker tag "$image_id" "alertflow-$service:${ALERTFLOW_GIT_COMMIT:-dev}"
    done < "$backup_dir/images.txt"
fi
docker compose up -d --no-build
curl -fsS http://127.0.0.1:8000/api/health

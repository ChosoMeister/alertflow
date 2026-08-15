#!/bin/sh
set -eu

project_dir=${ALERTFLOW_PROJECT_DIR:-/docker/alertflow}
backup_root=${ALERTFLOW_BACKUP_ROOT:-/docker/alertflow-backups}
release=${ALERTFLOW_RELEASE:-$(tr -d '\n' < "$project_dir/VERSION")}
git_commit=${ALERTFLOW_GIT_COMMIT:-$(git -C "$project_dir" rev-parse HEAD 2>/dev/null || printf '%s' unknown)}
export ALERTFLOW_RELEASE="$release"
export ALERTFLOW_GIT_COMMIT="$git_commit"
backup_dir="$backup_root/release-$release-$(date +%Y%m%d%H%M%S)"

mkdir -p "$backup_dir"
cp "$project_dir/docker-compose.yml" "$project_dir/VERSION" "$backup_dir/"
printf 'ALERTFLOW_RELEASE=%s\nALERTFLOW_GIT_COMMIT=%s\n' "$release" "$git_commit" > "$backup_dir/release.env"
tar -C "$project_dir" --exclude=.git --exclude=.env --exclude='._*' -czf "$backup_dir/source.tar.gz" .
docker run --rm -v alertflow_redis_data:/source:ro -v "$backup_dir":/backup redis:7-alpine tar -C /source -czf /backup/redis-data.tar.gz .

cd "$project_dir"
docker compose config >/dev/null
for service in smtp-ingestor alert-processor api-server web-ui; do
    image_id=$(docker compose images -q "$service" 2>/dev/null || true)
    if [ -n "$image_id" ]; then
        printf '%s %s\n' "$service" "$image_id" >> "$backup_dir/images.txt"
    fi
done
# Build immutable commit-tagged images before replacing any running container.
docker compose build
docker compose up -d --no-build

i=0
while [ "$i" -lt 30 ]; do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null && curl -fsS http://127.0.0.1:3100/ready >/dev/null; then
        docker builder prune -f --filter "until=168h" >/dev/null
        find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name 'release-*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR>2 {sub(/^[^ ]+ /, ""); print}' | xargs -r rm -rf
        printf '{"release":"%s","commit":"%s","deployed_at":"%s","backup":"%s"}\n' \
            "$release" "$git_commit" "$(date --iso-8601=seconds)" "$backup_dir" > "$project_dir/.alertflow-release.json"
        printf '%s\n' "Release $release deployed atomically; rollback snapshot: $backup_dir"
        exit 0
    fi
    i=$((i + 1))
    sleep 2
done

printf '%s\n' "Health gate failed; automatically restoring the previous images." >&2
"$project_dir/scripts/rollback.sh" "$backup_dir"
exit 1

#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$root/.gradle-qg}"
mkdir -p "$GRADLE_USER_HOME"
mkdir -p "$root/.m2-qg"
maven_arg="-Dmaven.repo.local=$root/.m2-qg"

cd "$root/apps/kramerius"
bash ./gradlew :installation:copySolr9search_sa :installation:copySolr9processing_sa :installation:copySolr9logs_sa :installation:copySolr9monitor_sa --no-daemon

stage="$root/local/solr/cores"
mkdir -p "$stage"
for core in search processing logs monitor; do
  source_dir="$root/apps/kramerius/installation/build/solr-9.x/$core"
  test -f "$source_dir/conf/managed-schema"
  mkdir -p "$stage/$core/conf"
  cp "$source_dir/core.properties" "$stage/$core/"
  cp "$source_dir/solrconfig.xml" "$stage/$core/conf/"
  cp -a "$source_dir/conf/." "$stage/$core/conf/"
  for resource in "$source_dir"/*.txt "$source_dir"/*.dic "$source_dir"/*.aff; do
    if test -f "$resource"; then cp "$resource" "$stage/$core/conf/"; fi
  done
done
docker build -t qg-solr:9.6.1 "$root/local/solr"
docker build -t qg-images:1 "$root/local/images"

if test "${QG_BUILD_MODE:-source}" = source; then
  cd "$root/apps/hazelcast-locks-server"
  bash ./gradlew publishToMavenLocal jibDockerBuild "$maven_arg" --no-daemon
  cd "$root/apps/akubra"
  bash ./gradlew publishToMavenLocal "$maven_arg" --no-daemon
  process_source="$root/.build-qg/process-platform-1.5.2"
  if ! test -f "$process_source/gradlew"; then
    mkdir -p "$process_source"
    git -C "$root/apps/process-platform" archive v1.5.2 | tar -x -C "$process_source"
  fi
  cd "$process_source"
  bash ./gradlew :process-common:publishToMavenLocal :process-api:publishToMavenLocal \
    :process-worker:publishToMavenLocal :process-manager:jibDockerBuild "$maven_arg" --no-daemon
  cd "$root/apps/kramerius"
  bash ./gradlew :search:jibDockerBuild :processes:platform:curator:worker:buildWorker \
    :processes:platform:curator:worker:jibDockerBuild \
    "$maven_arg" --no-daemon
else
  for image in ceskaexpedice/kramerius:7.2.3 ceskaexpedice/curator-worker:7.2.3 \
    ceskaexpedice/process-manager:1.5.2 ceskaexpedice/hazelcast-locks-server:2.0; do
    docker pull "$image"
  done
fi

docker image inspect --format '{{.RepoTags}} {{.Id}}' \
  qg-solr:9.6.1 qg-images:1 ceskaexpedice/kramerius:7.2.3 \
  ceskaexpedice/curator-worker:7.2.3 ceskaexpedice/process-manager:1.5.2 \
  ceskaexpedice/hazelcast-locks-server:2.0

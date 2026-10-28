#!/usr/bin/env bash
# Move only generated Gradle caches and build directories to /tmp when home is full.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
scratch="${QG_BUILD_SCRATCH:-/tmp/qg-build}"
mkdir -p "$scratch/gradle" "$scratch/projects"
if test -d "$root/.gradle-qg" && ! test -L "$root/.gradle-qg"; then
  mv "$root/.gradle-qg" "$scratch/gradle/home"
  ln -s "$scratch/gradle/home" "$root/.gradle-qg"
fi
while IFS= read -r build_dir; do
  relative=${build_dir#"$root/apps/kramerius/"}
  destination="$scratch/projects/$relative"
  mkdir -p "$(dirname "$destination")"
  mv "$build_dir" "$destination"
  ln -s "$destination" "$build_dir"
done < <(find "$root/apps/kramerius" -type d -name build -prune)
df -h "$root" "$scratch"

#!/usr/bin/env bash
set -euo pipefail

review_root=$(cd "$(dirname "$0")/../../.." && pwd)
source_root=${KRAMERIUS_REVIEW_SOURCE_ROOT:-$review_root}
if [[ ! -f "$source_root/kramerius/search/src/java/cz/incad/Kramerius/imaging/IiifServlet.java" || ! -d "$source_root/akubra" ]]; then
  echo "Set KRAMERIUS_REVIEW_SOURCE_ROOT to a workspace containing kramerius/ and akubra/" >&2
  exit 1
fi
cd "$source_root"
build_dir=/tmp/kramerius-source-calls
mkdir -p "$build_dir"
javac -d "$build_dir" "$review_root/review/raw/tools/SourceCalls.java"
java -cp "$build_dir" SourceCalls \
  kramerius/search/src/java/cz/incad/Kramerius/imaging/IiifServlet.java \
  kramerius/shared/common/src/main/java/cz/incad/kramerius/iiif/IIIFUtils.java \
  kramerius/shared/common/src/main/java/cz/incad/kramerius/statistics/accesslogs/AggregatedAccessLogs.java \
  kramerius/shared/common/src/main/java/cz/incad/kramerius/statistics/accesslogs/solr/SolrStatisticsAccessLogImpl.java \
  akubra/src/main/java/org/ceskaexpedice/akubra/impl/AkubraRepositoryImpl.java \
  akubra/src/main/java/org/ceskaexpedice/akubra/impl/RelsExtHelperImpl.java \
  kramerius/search/src/java/cz/incad/Kramerius/backend/guice/BaseModule.java \
  > "$review_root/review/raw/iiif-source-calls.tsv"
KRAMERIUS_REVIEW_SOURCE_ROOT="$source_root" python3 "$review_root/review/raw/tools/render_iiif_graph.py"

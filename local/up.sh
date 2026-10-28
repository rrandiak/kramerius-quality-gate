#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
if ! k3d cluster list --no-headers | awk '{print $1}' | grep -qx qg; then
  mkdir -p /tmp/qg-k3s
  k3d cluster create qg --servers 1 --agents 0 \
    --volume /tmp/qg-k3s:/var/lib/rancher/k3s@server:0 --wait
fi
mkdir -p "$root/.build-qg"
export KUBECONFIG="$root/.build-qg/kubeconfig-qg.yaml"
k3d kubeconfig get qg > "$KUBECONFIG"
test "$(kubectl config current-context)" = k3d-qg
kubectl create namespace qg --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace qg app.kubernetes.io/managed-by=Helm --overwrite
kubectl annotate namespace qg meta.helm.sh/release-name=qg meta.helm.sh/release-namespace=qg --overwrite
kubectl apply -f "$root/local/storage.yaml"
agent="$root/.build-qg/opentelemetry-javaagent-2.8.0.jar"
if ! test -f "$agent"; then
  mkdir -p "$root/.build-qg"
  curl --fail --location --silent --show-error \
    https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.8.0/opentelemetry-javaagent.jar \
    -o "$agent"
fi
docker exec k3d-qg-server-0 mkdir -p /qg/javaagents /qg/traces
docker cp "$agent" k3d-qg-server-0:/qg/javaagents/opentelemetry-javaagent.jar
k3d image import qg-solr:9.6.1 qg-images:1 \
  ceskaexpedice/kramerius:7.2.3 ceskaexpedice/curator-worker:7.2.3 \
  ceskaexpedice/process-manager:1.5.2 ceskaexpedice/hazelcast-locks-server:2.0 -c qg
kubectl apply -f "$root/local/dependencies.yaml"
kubectl -n qg rollout status deployment/qg-solr --timeout=5m
kubectl -n qg rollout status deployment/qg-images --timeout=5m
kubectl -n qg rollout status deployment/qg-keycloak --timeout=5m
kubectl -n qg rollout status deployment/otel-collector --timeout=5m
helm upgrade --install qg "$root/apps/kramerius-helm-chart" -n qg \
  -f "$root/local/values.yaml" \
  --set-file "krameriusPublic.customConfigs[0].content=$root/local/lp.xml" \
  --set-file "krameriusCurator.customConfigs[0].content=$root/local/lp.xml" \
  --wait --timeout 15m
kubectl -n qg get pods -o wide

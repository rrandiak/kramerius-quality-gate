#!/usr/bin/env python3
"""Render a focused IIIF call graph from SourceCalls' AST-derived edges."""

import csv
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = Path(os.environ.get("KRAMERIUS_REVIEW_SOURCE_ROOT", ROOT))
TSV = ROOT / "review/raw/iiif-source-calls.tsv"
DOT = ROOT / "review/raw/iiif-info-callgraph.dot"
SVG = ROOT / "review/raw/iiif-info-callgraph.svg"

with TSV.open(newline="") as source:
    calls = list(csv.DictReader(source, delimiter="\t"))


def call(caller, receiver, callee):
    matches = [row for row in calls if row["caller"] == caller
               and row["receiver"] == receiver and row["callee"] == callee]
    if not matches:
        raise ValueError(f"Missing source call: {caller} -> {receiver}.{callee}")
    return matches[0]["location"].rsplit(":", 1)[-1]


def edge(source, target, line=None, style=None, annotation=None):
    attributes = []
    label = annotation or (f"line {line}" if line else None)
    if label:
        attributes.append(f'label="{label}"')
    if style:
        attributes.append(f'style="{style}"')
    suffix = f" [{', '.join(attributes)}]" if attributes else ""
    return f'  "{source}" -> "{target}"{suffix};'


binding = (SOURCE_ROOT / "kramerius/search/src/java/cz/incad/Kramerius/backend/guice/BaseModule.java").read_text()
if 'Names.named("solr-statistics")).to(SolrStatisticsAccessLogImpl.class)' not in binding:
    raise ValueError("Expected production Guice binding was not found")

lines = [
    'digraph IIIFInfo {',
    '  rankdir=LR;',
    '  graph [fontname="DejaVu Sans", label="IIIF info.json — selected source calls", labelloc=t];',
    '  node [shape=box, fontname="DejaVu Sans", fontsize=10];',
    '  edge [fontname="DejaVu Sans", fontsize=9];',
    '  "GET /search/iiif/{pid}/info.json" [shape=oval];',
    '  "cdk.server.mode" [shape=diamond];',
    '  "Source Kramerius" [shape=cylinder];',
    '  "Image server" [shape=cylinder];',
    '  "Solr" [shape=cylinder];',
    '  "Akubra / FOXML" [shape=cylinder];',
    edge("GET /search/iiif/{pid}/info.json", "IiifServlet.doGet", style="dashed"),
    edge("IiifServlet.doGet", "cdk.server.mode", style="dashed"),
    edge("cdk.server.mode", "IiifServlet.proxyInfoJson", style="dashed", annotation="true"),
    edge("cdk.server.mode", "SolrAccess.getPidPaths", style="dashed", annotation="false"),
    edge("IiifServlet.doGet", "IiifServlet.proxyInfoJson",
         call("IiifServlet.doGet", "IiifServlet", "proxyInfoJson")),
    edge("IiifServlet.proxyInfoJson", "Source Kramerius",
         call("IiifServlet.proxyInfoJson", "apacheClient.get()", "execute")),
    edge("IiifServlet.doGet", "SolrAccess.getPidPaths",
         call("IiifServlet.doGet", "SolrAccess", "getPidPaths")),
    edge("IiifServlet.doGet", "RightsResolver.isActionAllowed",
         call("IiifServlet.doGet", "RightsResolver", "isActionAllowed")),
    edge("IiifServlet.doGet", "IIIFUtils.iiifImageEndpoint",
         call("IiifServlet.doGet", "IIIFUtils", "iiifImageEndpoint")),
    edge("IIIFUtils.iiifImageEndpoint", "AkubraRepository.re().getTilesUrl",
         call("IIIFUtils.iiifImageEndpoint", "akubraRepository.re()", "getTilesUrl")),
    edge("AkubraRepository.re().getTilesUrl", "RelsExtHelperImpl.getTilesUrl", style="dashed"),
    edge("RelsExtHelperImpl.getTilesUrl", "Akubra / FOXML",
         call("RelsExtHelperImpl.getTilesUrl", "AkubraRepository", "get")),
    edge("IiifServlet.doGet", "IiifServlet.reportAccess",
         call("IiifServlet.doGet", "IiifServlet", "reportAccess")),
    edge("IiifServlet.reportAccess", "AggregatedAccessLogs.reportAccess",
         call("IiifServlet.reportAccess", "AggregatedAccessLogs", "reportAccess")),
    edge("AggregatedAccessLogs.reportAccess", "StatisticsAccessLog.reportAccess",
         call("AggregatedAccessLogs.reportAccess", "StatisticsAccessLog", "reportAccess")),
    edge("StatisticsAccessLog.reportAccess", "SolrStatisticsAccessLogImpl.reportAccess", style="dashed"),
    edge("SolrStatisticsAccessLogImpl.reportAccess", "SolrAccess.getSolrDataByPid",
         call("SolrStatisticsAccessLogImpl.reportAccess", "SolrAccess", "getSolrDataByPid")),
    edge("SolrAccess.getSolrDataByPid", "Solr", style="dashed"),
    edge("SolrStatisticsAccessLogImpl.reportAccess", "AkubraRepository.get",
         call("SolrStatisticsAccessLogImpl.reportAccess", "AkubraRepository", "get")),
    edge("AkubraRepository.get", "Akubra / FOXML", style="dashed"),
    edge("SolrStatisticsAccessLogImpl.reportAccess", "SolrUpdateUtils.sendToDest",
         call("SolrStatisticsAccessLogImpl.reportAccess", "SolrUpdateUtils", "sendToDest")),
    edge("SolrUpdateUtils.sendToDest", "Solr", style="dashed"),
    edge("IiifServlet.doGet", "RESTHelper.openConnection",
         call("IiifServlet.doGet", "RESTHelper", "openConnection")),
    edge("RESTHelper.openConnection", "Image server", style="dashed"),
    '  subgraph cluster_legend {',
    '    label="Solid: AST call; dashed: route, branch, binding, or external boundary";',
    '    color=gray;',
    '  }',
    '}',
]
DOT.write_text("\n".join(lines) + "\n")
subprocess.run(["dot", "-Tsvg", str(DOT), "-o", str(SVG)], check=True)
print(f"Wrote {DOT.relative_to(ROOT)} and {SVG.relative_to(ROOT)}")

# Kramerius architecture and performance review

A review of Kramerius 7, Akubra and process-platform, done at MZK (Moravian Library in Brno). Start with
[`review/README.md`](review/README.md): it indexes the results to present (bugs, bugs already known upstream, web client
bugs, performance and quality-of-life proposals) and explains how far they have been verified. The evidence behind them is
in [`review/raw/`](review/raw/): numbered reports with the source analysis and bounded, read-only production
observations, plus diagrams and the tool that generates the IIIF call graph.

Most findings were produced with an AI coding agent and have not yet been confirmed by an MZK programmer; see the
disclaimer at the top of `review/README.md`.

## Revisions

The findings cite source lines on these commits; deployed images may differ. Individual reports name the revision they
used where it differs.

| Repository | Commit |
| --- | --- |
| Kramerius | `560676c85d276bd53f2dbaae95e87ddc6abd6e07` |
| Akubra | `51d821bcb55b89050e834ea00651aeb051146495` |
| process-platform | `976dc4b12c0592ba1ed0afea72558061619afa17` (some earlier reports: `da88e6a2ff7f210b2f1dda848a91c90ba99c1df3`) |

## IIIF call graph

The source call graph in `review/raw/` uses an AST helper, Python and Graphviz. To rebuild it, set
`KRAMERIUS_REVIEW_SOURCE_ROOT` to a directory containing `kramerius/` and `akubra/` checkouts and run
`review/raw/tools/build_iiif_callgraph.sh`; the script writes the graph outputs into `review/raw/`. The graph captures
selected source calls and annotated boundaries, not runtime timing or full dynamic dispatch.

---
id: KB-014
former_id: BUG-042
category: known-bug
title: Thumbnail and preview reads use the first external datastream version
area: storage
severity: medium
effort: S
use_cases: [image-open, storage]
review_ref: [GH1]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1287
checked: [source, upstream-report]
checked_how: "Read the datastream SAX handler at Akubra 51d821b; kramerius#1287; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-014 — Thumbnail and preview reads use the first external datastream version

> **In one sentence:** an object with multiple externally referenced image versions can display its old thumbnail or preview.

**GitHub issue verification:** this report checks [upstream issue #1287](https://github.com/ceskaexpedice/kramerius/issues/1287) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream report describes `IMG_THUMB` and `IMG_PREVIEW` using version `.0` even when a later version exists.

## Cause

Akubra `GetDatastreamContentSaxHandler.java:240–257@51d821bcb55b89050e834ea00651aeb051146495` throws its `FOUND` sentinel as soon as it sees the first `contentLocation` in the requested datastream. `RepositoryUtils.java:113–144@51d821bcb55b89050e834ea00651aeb051146495` accepts that early stop and reads its URL, so later versions are not considered. Kramerius `ItemsResource.java:1924–1949@560676c85d276bd53f2dbaae95e87ddc6abd6e07` calls this path for thumb and preview images. Akubra's separate `RepositoryUtils.getLastStreamVersion` helper at line 83 already defines the intended last-version behavior.

## Evidence and frequency

Source-confirmed at the named revisions. The [upstream issue](https://github.com/ceskaexpedice/kramerius/issues/1287) reports an affected object; this review did not inspect its content or count affected objects in MZK.

## Impact

Readers can see stale representative images; an unavailable first-version URL can also prevent a valid newer preview from loading.

## Fix

Parse all versions and select the last version's content reference consistently with `getLastStreamVersion`; keep the selected version's MIME type and content together.

## Test

Use an in-memory FOXML object containing two external image versions with distinct references. Assert that both thumb and preview retrieval choose the later version.

## Related

- [GH1 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).

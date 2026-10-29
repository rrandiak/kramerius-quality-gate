---
id: BUG-030
former_id: null
category: bug
title: When the users database is down while Kramerius starts, it starts anyway without its lifecycle services, and IIIF tiles fail with 500 until a manual restart
area: operations
severity: high
effort: S                # make a StartupServlet failure fail the context; start lifecycle services independently of DB setup
touches: [search]
contracts: []
data_migration: false
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read StartupServlet, UsersConnectionProvider, AbstractImageServlet, IiifServlet at Kramerius 560676c; MZK 2026-10-29: Tomcat logs of both public pods (every start, lifecycle lines, 52,524 'Request execution cancelled'), NGINX tile status, traces of failing vs working tiles; Tomcat logs since 2026-09-29"
checked_on: 2026-10-29
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-030 — When the users database is down while Kramerius starts, it starts anyway without its lifecycle services, and IIIF tiles fail with 500 until a manual restart

> **In one sentence:** if Kramerius starts while the users database is unreachable (at MZK, when a Kubernetes node update
> restarts pods and databases at the same time), `StartupServlet` fails before it starts the lifecycle services, but
> Tomcat starts the application anyway; the pod is Ready and serves search, thumbnails and metadata, while every IIIF tile
> fails with 500 because the image-server client was never started, until someone restarts the pod.

## Symptom

Readers open a page and see only a blurry image that never sharpens. Both web clients draw the page thumbnail
(`items/{pid}/image/thumb`) stretched under the IIIF tile layer as a placeholder (new client
`kramerius-web-client-v3` `iiif-viewer.ts:339–379`, old client `kramerius-web-client` `viewer.component.ts:1124–1165`).
`info.json` loads, so the viewer opens, but every tile request answers 500, so the placeholder stays. Neither client falls
back to another image when tiles fail; the new one only does so when `info.json` fails.

Everything else works: search, metadata, thumbnails, previews, rights checks. The pods are Running and Ready. MZK operators
restart kramerius-public by hand, which helps.

The Tomcat log has one line per failed tile:

```
SEVERE [http-nio-8080-exec-9] cz.incad.Kramerius.imaging.IiifServlet.doGet java.util.concurrent.CancellationException: Request execution cancelled
    java.io.IOException: java.util.concurrent.CancellationException: Request execution cancelled
        at cz.incad.Kramerius.AbstractImageServlet.copyFromImageServer(AbstractImageServlet.java:258)
        at cz.incad.Kramerius.imaging.IiifServlet.doGet(IiifServlet.java:195)
```

and, at the start that caused it, a failed `StartupServlet.init` (`UsersConnectionProvider.get The connection attempt
failed`, `StartupServlet.init Unable to provision`) followed by `Server startup in […] milliseconds`, with no
`Starting Http async client` line.

## Cause

Kramerius `origin/master` at `560676c`:

1. `StartupServlet` is a servlet with `load-on-startup` 1 (`search/web/WEB-INF/web.xml:292–296`). Its `init()` opens the
   Kramerius and the users database connections (`search/src/java/cz/incad/Kramerius/StartupServlet.java:95–96`), runs the
   schema initializers, and only at the very end starts the lifecycle services: `pdfService.init()` and
   `lifecycleRegistry.startNotification()` (`StartupServlet.java:148–149`).
2. When the users database is unreachable, `UsersConnectionProvider.get` throws
   (`shared/common/src/main/java/cz/incad/kramerius/database/provider/UsersConnectionProvider.java:61–66`), and `init()`
   ends with `RuntimeException("Failed to start Kramerius")` (`StartupServlet.java:151–153`). The code even treats the
   users connection as optional (`if (usersConnection != null)`, `:125`), but the provider never returns `null`.
3. An exception from a servlet's `init()` only makes that servlet unavailable; Tomcat still starts the `/search` context.
   The application serves requests without its lifecycle services. On 2026-10-29 the registry would have started the
   shared image-server `HttpAsyncClient`, the process schedulers, the Keycloak CDK cache and the CDK API-key hook.
4. IIIF tiles are fetched through that `HttpAsyncClient` (`AbstractImageServlet.copyFromImageServer`,
   `search/src/java/cz/incad/Kramerius/AbstractImageServlet.java:199–257`; Guice singleton, `BaseModule.java:109`, started
   only by `HttpAsyncClientLifeCycleHook.java:26`). A client that was never started rejects every request at once with
   `CancellationException: Request execution cancelled`, and `IiifServlet` turns that into a bare 500
   (`IiifServlet.java:208–213`).
5. Nothing ever retries the start. `info.json` (fresh `HttpURLConnection`, `IiifServlet.java:183–184`) and thumbnails
   (read from Akubra) do not use the client, so they keep working, which hides the failure.

By contrast, when the **Kramerius** database is down at start, the failure happens in a context listener, Tomcat logs
`Context [/search] startup failed`, and the pod is restarted until the database is back: the safe behaviour. Seen at
MZK the same morning, 08:48–08:53 local time.

## Evidence and frequency

MZK production, 2026-10-29. Times are local (CET); UTC is one hour earlier. A node update between ~03:10 and ~04:00
restarted the public pods several times and also restarted the databases (`process-db-1` at 03:53, `users-db-1` at 05:42;
`users-db-1` had 30 restarts at that point).

| Pod | Start | Users DB at start | Lifecycle services started? | Then |
| --- | --- | --- | --- | --- |
| public-0 | 03:15 | up | yes | tiles OK |
| public-0 | **03:55** | **unreachable** (`StartupServlet.java:96`) | **no** | tile 500s from 03:57 to 08:54: 37,422 |
| public-0 | 08:54 (manual restart) | up | yes | tiles OK |
| public-1 | 03:04, 04:20, 04:38 | up | yes | tiles OK |
| public-1 | **05:40** | **unreachable** (`StartupServlet.java:96`) | **no** | tile 500s from 05:45 to 08:47: 15,102 |
| public-1 | 08:48–08:52 | Kramerius DB down (manual restart) | — | context failed, pod restarted 3× |
| public-1 | 08:54 | up | yes | tiles OK |

In NGINX: 52,523 IIIF tile 500s from 03:50 to 08:53 (67–82 % of tiles per hour; 100 % between 05:45 and ~06:30, when
both pods were affected). CDK forward IIIF requests answered 100 % 5xx from 06:00 to 08:00. In the traces, the failing tile
requests pass the rights check (including its Postgres queries), Solr and Akubra, never call the image server, and end in
`sendError` within ~73 ms; the working ones call the image server once per tile.

**How often:** MZK operators say it happens often after Kubernetes node updates, and that a restart is the known
remedy. The Tomcat logs on both pods go back to 2026-09-29, and only 2026-10-29 has `Request execution cancelled`;
earlier episodes, if any, are older than the logs. It needs a pod to start exactly while the users database is down.

## Impact

High for readers: for five hours most pages could not be zoomed on the public site, and CDK users of MZK's collections were
affected through the forward endpoint. Nothing alerts on it: the pods stay Ready, and the failure shows only in NGINX status
codes and the Tomcat log. The other lifecycle services (process schedulers, CDK caches, PDF service) were also not
started; what that broke was not measured.

## Fix

1. **Fail the start, not one servlet.** Move the database initialization and `startNotification()` from
   `StartupServlet.init` into a `ServletContextListener`, so a database outage at start fails `/search` like the
   Kramerius-DB case does, and the pod restarts until the database is back. **Workaround without a code change:** set
   `failCtxIfServletStartFails="true"` on the `/search` `<Context>` (Tomcat 9), which makes Tomcat fail the context when a
   load-on-startup servlet throws.
2. Or, if the users database is meant to be optional, make `UsersConnectionProvider` return `null` when it cannot connect
   (as `StartupServlet.java:125` expects), and start the lifecycle services even when an initializer fails.
3. **Health check:** expose "startup completed" (and the image client's state) to the readiness probe, so a half-started
   pod gets no traffic.
4. Log `Request execution cancelled` once with a clear cause ("image-server client not running") instead of one SEVERE
   stack per tile.

## Test

- Start Kramerius with the users database unreachable. Before the fix: `/search` starts, `GET /search/iiif/<pid>/…/default.jpg`
  answers 500 with `Request execution cancelled`. After the fix: the context fails to start (or, with fix 2, tiles load).
- Start with both databases up: the log has `Starting Http async client` and tiles load (no change).

## Missing upstream

Not reported. A new issue in `kramerius` should state:

- `StartupServlet.init` (`StartupServlet.java:95–153` at `560676c`) opens the users database before it starts the
  lifecycle services; when that fails it throws, Tomcat marks only that servlet unavailable and starts `/search` anyway, so
  the image-server `HttpAsyncClient`, process schedulers and CDK hooks never start.
- Result at MZK on 2026-10-29: two public pods started during a users-database restart and answered every IIIF tile with
  500 (`CancellationException: Request execution cancelled`, `AbstractImageServlet.copyFromImageServer`) for 3–5 hours,
  while staying Ready, until they were restarted by hand.
- Fix: fail the context on a startup failure (or make the users DB truly optional and start the lifecycle services
  regardless), and expose startup state to a health check.

## Related

- [BUG-026](BUG-026-iiif-500-for-objects-without-tiles.md): the same servlet's other bare-500 path.
- [QOL-001](../quality-of-life/QOL-001-otel-in-images-replace-monitor-core.md): metrics that would have alerted on this.
- A web client entry could follow: neither client falls back or tells the reader when tiles fail and `info.json` works.

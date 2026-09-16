# Architecture

This document explains _why_ the codebase is shaped the way it is, not just _what_ it contains. Each section describes a decision, the constraint that forced it, and the conditions under which the decision should be revisited.

The audience is someone copying this template, extending it, or wondering whether some subsystem is naive or deliberate. In most cases, it's deliberate. This document says which.

---

## 1. The high-level shape

```
┌─────────────────────────────────────────┐
│  Tauri 2 (Rust host)                    │
│  ├─ WebView (Svelte 5 + SvelteKit-less) │
│  └─ Sidecar supervisor (src/sidecar.rs) │
└──────────────┬──────────────────────────┘
               │ spawns, reads READY, probes /health
               ▼
┌─────────────────────────────────────────┐
│  Python sidecar (PyInstaller onefile)   │
│  ├─ FastAPI + uvicorn on 127.0.0.1:0    │
│  ├─ In-process JobManager               │
│  └─ Polars analytics pipeline           │
└─────────────────────────────────────────┘
```

Three processes at runtime (Tauri host, WebView, sidecar) or four in dev (`uv run python -m app.main`). Nothing else.

The WebView talks HTTP directly to the sidecar; Rust does not proxy. Rust's job is _lifecycle_ — spawn, handshake, shutdown — plus a small set of privileged filesystem commands. This split exists because the WebView is the natural place for UI logic and the sidecar is the natural place for analytics; putting Rust in the middle would add a layer with no purpose.

---

## 2. Process model: the sidecar

**Decision:** one Python process, spawned by Rust, communicating over local HTTP with a bearer token.

**Files:** `src-tauri/src/sidecar.rs`, `src-python/app/main.py`

### The READY handshake

Rust spawns the sidecar with `SIDECAR_TOKEN=<uuid> --data-dir <dir> --port 0`. Python binds to `127.0.0.1:0` (OS-chosen port), prints exactly `READY <port>` on stdout with `flush=True`, then serves. Rust reads stdout, parses the port, polls `GET /health` until it responds, and only then stores `{port, token}` and emits `backend-ready` to the WebView.

The handshake is the whole reason this works on Windows. A PyInstaller onefile bootloader can take several seconds to extract and start; the OS-chosen port avoids conflicts with any other app the user has running; and probing `/health` before announcing readiness means the frontend never sees a URL that isn't actually serving.

**Detail that matters:** the READY line goes to stdout, everything else to stderr. `config.py` logs the ephemeral-token warning to stderr specifically so it can never be mistaken for the handshake. If you add a debug print, put it on stderr.

### Auth

The token is generated per-launch by Rust (`uuid::Uuid::new_v4()`) and passed via environment. Python compares it with `secrets.compare_digest`. Every route except `/health` requires it. The token never reaches the DOM; the frontend's `backend.svelte.ts` store keeps it in module scope and exposes only `backend.headers` to the API client.

This is not network security — the server is bound to loopback, so the threat model is "another process on the same machine." The token exists so a random local process scanning for open ports can't query chat analytics or trigger jobs.

### Shutdown

`POST /shutdown` is the **primary** mechanism. `kill()` is a fallback.

The reason is PyInstaller. In onefile mode, the process Rust spawns is the _bootloader_, not the real Python server. Killing the bootloader orphans the child that actually holds the port. So the shutdown protocol is: Rust POSTs `/shutdown`, Python sets `server.should_exit = True` and signals running jobs to abort at their next progress checkpoint, uvicorn exits cleanly, the bootloader cleans up its extraction directory, and the port is released.

Rust polls for up to 3 seconds, then force-kills on Windows via `taskkill /T` (which walks the process tree) or via direct `kill()` on Unix. The 3-second window exists because force-killing a bootloader mid-cleanup leaves a `%TEMP%\_MEIxxxxxx` directory behind, which is annoying but not fatal.

### Dev mode

When `SIDECAR_DEV=1`, Rust spawns `uv run --project src-python python -m app.main` via `std::process::Command` instead of the bundled binary. This gives hot-reload on Python changes without a PyInstaller cycle, and it doesn't require the shell-plugin capability because it's not going through the sandboxed shell API.

The dev child is tracked separately (`DevChild` state) so shutdown can kill it too. Note that the ready-handshake stdout parsing is duplicated between the two paths — bundled uses `CommandEvent::Stdout` from the shell plugin's event stream, dev uses `BufReader::lines()`. Both need partial-line buffering; the bundled path accumulates in a `String` and drains on `\n`, the dev path uses the standard library's line iterator.

### When to reconsider

- If the sidecar ever needs to bind to a non-loopback interface (e.g., for a LAN debug tool), the current token-in-env model stops being sufficient.
- If multiple sidecars need to run concurrently (one per channel?), the READY-on-stdout protocol becomes ambiguous and would need to move to a file or socket.
- If PyInstaller onefile startup ever becomes a hard problem, the fallback is a pre-extracted onedir — but see §7 for why that breaks the Tauri bundler.

---

## 3. Jobs: in-process, not distributed

**Decision:** background work runs in daemon threads inside the sidecar, coordinated by a `JobManager` that lives in Python memory.

**Files:** `src-python/app/core/jobs.py`, `src-python/app/routers/jobs.py`

### Why in-process

The problem this solves: a `chat_stats` fetch for a 10-year channel can take 10–45 minutes. That's too long to hold an HTTP connection open, so something has to run in the background and stream progress.

The `JobManager` gives each job:

- A `threading.Lock`-guarded dict of job state
- A ring buffer of progress events (`deque(maxlen=500)`) with monotonic sequence numbers so a stalled SSE consumer never grows memory
- Retention bounds (`MAX_JOB_HISTORY=20`, `MAX_JOB_AGE_S=4h`) so abandoned jobs don't accumulate
- Cooperative shutdown via `InterruptedError` raised at progress callbacks
- An `ack` endpoint the client calls after consuming a result, releasing the (potentially large) payload

Scripts run in `daemon=True` threads so sync code (like a `time.sleep(0.05)` in `example_task`) never blocks the event loop.

### SSE, not polling

The frontend uses Server-Sent Events over `fetch` streaming (`readSSE` in `client.ts`), not the `EventSource` API — because `EventSource` can't send the `Authorization` header. Frames are `data:` lines per progress event and a terminal `event: done|error` frame carrying the final `JobStatus`.

**Heartbeats.** Every 15 seconds of idle stream, the server emits `: heartbeat\n\n`. This is an SSE comment frame; clients must ignore it. We do it because some Windows loopback proxies and antivirus tools prune connections that go quiet for ~30s, and a 45-minute fetch has many quiet moments.

**Cancel.** The frontend passes an optional `AbortSignal` into `waitJob`. Aborting detaches the _waiter_, not the _job_. The Python job keeps running and continues writing to `log_cache`, so a cancelled run's partial work is not wasted — the next run resumes from cache. The waiter rejects with a distinct `JobCancelledError` (not a timeout error), and _does not ack_, so the eventual result stays retained server-side.

**Fallback to polling.** If the SSE stream breaks (proxy hiccup, WebView quirk), `waitJob` catches the transport error and polls `GET /api/jobs/{id}` every 1.5s until the job reaches a terminal state. A broken stream is not a job failure.

### Why _not_ Celery + Redis

This is the decision people ask about most, so it deserves a straight answer.

**For a web service deployed to a server, Celery+Redis is correct.** It provides cross-process durability, horizontal scaling, and a well-known monitoring surface. None of that is controversial.

**This is a desktop app.** The cost of adding Celery+Redis here is:

- **A second signed binary** (Redis is a C daemon). The release pipeline (`release.yml`) validates a single sidecar per platform, signs it before `tauri build`, and sets `SIDECAR_PREBUILT=1` so the build doesn't rebuild and clobber the signature. Every additional binary multiplies that work on Windows, macOS aarch64, and Linux.
- **Three processes at runtime** with three lifecycle stories. Today Rust spawns one child and reads one READY line. Redis+worker means a supervisor, port-conflict handling for 6379, and a second shutdown protocol.
- **Replacement, not augmentation, of the JobManager.** `AsyncResult` and the result backend own retention; the SSE generator would poll Redis instead of an in-memory deque. The current code isn't "topped up" — it goes away. That's a smaller codebase, but it's a different set of failure modes (Redis unavailable, worker crash, broker redelivery).
- **A large benefit that the deployment doesn't use.** No horizontal scaling needed on a single-user machine. No cross-machine durability needed — the app doesn't run when it's closed.

The line is: **do we need job state to survive a sidecar restart?** Today, no. `log_cache` preserves _fetched data_, but in-flight jobs are lost on restart. If that ever becomes a requirement — "close the app, reopen, the fetch continues" — that's the trigger.

**When to migrate:**

- Multi-machine deployment (server + desktop client) becomes a real product direction.
- Jobs must survive sidecar restarts.
- Concurrent job count exceeds what a single thread pool can handle.
- The project's framing changes from "desktop template" to "web service with a desktop client."

Until then, the in-process `JobManager` is the _smallest correct pattern_ for the actual problem. A template that reaches for distributed job queues before it needs them teaches the wrong lesson.

**What to do instead:** add a comment block at the top of `core/jobs.py` describing the boundary. If a future maintainer hits the trigger, they should find the migration path documented in situ.

### When to reconsider

- Any of the migration triggers above.
- If progress events ever need to survive across sidecar restarts (currently they don't).
- If a single job's memory footprint grows beyond what one process can hold (see §5).

---

## 4. Data fetch and cache

**Decision:** fetch chat logs month-by-month, cache each month as a Parquet file with a JSON sidecar tracking coverage.

**Files:** `src-python/app/services/log_fetch.py`, `src-python/app/services/log_cache.py`, `src-python/app/scripts/chat_stats/fetcher.py`

### Why month chunking

Two reasons:

1. **Range shifts don't invalidate the cache.** Querying "Jan 1 – Mar 1" and then "Jan 15 – Mar 15" share two whole months. If the cache were keyed on exact ranges, the second query would miss entirely.
2. **Coverage is trackable per-unit.** A partially-fetched month is a meaningful state; a partially-fetched arbitrary range is not. The current design can say "we have Jan 2024 fully, Feb 2024 through the 15th" and only fetch the gap.

### Coverage intervals

Each month's JSON sidecar carries a `coverage` field: a list of `[from_iso, to_iso]` intervals. A month is `complete` only when a single interval spans the entire month and no contributing fetch truncated. This exists because upstream refusals (deep-offset 404s) can leave a span _partially_ fetched, and pretending it's whole would be worse than admitting the gap.

The `merge_coverage` function merges overlapping and touching intervals, so repeated top-ups don't grow the list unbounded.

### Immutability

A month is `immutable` once the _next_ month starts at least one hour in the past. Twitch chat is append-only, so a completed month's messages never change; only the current live month can receive new messages. This lets the cache short-circuit the freshness check for all historical months.

Immutability is re-evaluated at _load_ time, not _save_ time, so a chunk saved as live promotes itself once the month ages out.

### Live TTL

The current month's chunk is valid for 15 minutes (`LIVE_TTL_S`). After that, the fetcher re-opens it with `allow_stale=True`, computes the gap between `fetched_at` and `now`, and fetches only that tail — appending to the existing chunk rather than replacing it.

### Atomic writes

`save_month` writes to a `.tmp` file with a random suffix, then `os.replace`s it into place. The random suffix matters on Windows: two concurrent saves to the same month would otherwise share the same tmp path and raise `WinError 32`, or worse, interleave into a corrupt Parquet footer.

### Eviction

`MAX_CACHE_BYTES = 500MB`. Eviction runs at most once per hour (`EVICT_MIN_INTERVAL_S`), scanning the cache directory and deleting oldest entries by mtime until under the cap. Throttled because a full recursive scan on every save makes fetch latency a function of total cache size.

### Cache version

`CACHE_VERSION = "v4"`. When the frame schema changes, bump this and the loader will purge older versions on first touch. Without this, every version of the app could hoard up to `MAX_CACHE_BYTES` forever.

### When to reconsider

- If a month's Parquet file ever exceeds tens of MB, consider splitting further (weekly?).
- If a read of the cache ever becomes the bottleneck (it isn't — Parquet is fast), consider DuckDB on top.
- If coverage logic ever becomes the source of bug reports, the current "list of intervals" model has a simpler alternative: store `covered_from` and `covered_to` only, and refuse to cache non-contiguous fetches. The current model is more capable but harder to reason about.

---

## 5. Analytics pipeline

**Decision:** build one Polars DataFrame per run, fan it out to a set of independent analysis modules.

**Files:** `src-python/app/scripts/chat_stats/orchestrator.py` and `analytics/*.py`

### Frame once, feed many

The entry point is `compute_stats(df, params, emote_map)`. It calls into ~25 analysis modules, each returning a `dict` that gets merged into the result. Nothing mutates `df`; nothing shares state between modules except the frame itself.

Notable shared intermediates:

- `parse_twitch_emotes(df)` produces a `List(String)` Series used by emote counting, emote pairs, emote diversity, and message classification.
- `emote_pairs_frame(twitch_emotes)` feeds emote pairs and emote centrality.
- `mention_pairs_frame(df)` feeds mentions, mention graph, and mutual mentions.

Each is computed once and passed down. This is the main performance lever in the analytics path — computing these per-module would be 3–5× slower.

### Eager, not lazy

All analysis modules use eager `DataFrame` operations. A previous suggestion to convert to `LazyFrame` was declined: `pl.concat(parts).collect()` with no downstream lazy ops optimizes nothing. The analytics are a fan-out, not a pipeline — each module terminates in a `.sum()`, `.len()`, `.to_list()`, or similar. Lazy evaluation would only help if the whole thing were one query plan, which would sacrifice the module separation that makes the code readable.

If that separation ever becomes a liability (e.g., a single 60-second analysis that could be 5 seconds with a fused plan), revisit. Today it isn't.

### Where the fan-out is expensive

`compute_stats` on a 5M-message frame runs all modules sequentially. Some are trivially fast (aggregations on one column), some are heavy:

- `detect_anomalies` — `group_by_dynamic` over 5-minute windows
- `compute_copy_paste_chains` — self-join on text
- `compute_quote_replies` — `join_asof` against every message
- `compute_bot_scores` — per-user `diff()` over sorted timestamps

These are the modules to profile first if the analytics stage ever becomes the bottleneck. In practice it hasn't been — the _fetch_ dominates for large ranges.

### When to reconsider

- If any single module ever exceeds ~5 seconds on a realistic input, profile it with Polars' query profiler.
- If the full `compute_stats` exceeds the fetch time, parallelize across modules. Polars releases the GIL for most operations, so a `concurrent.futures.ThreadPoolExecutor` is a viable first step.
- If the frame ever doesn't fit in memory (say, 10M+ messages with many columns), consider a columnar on-disk intermediary or splitting analysis across sub-frames.

---

## 6. Frontend

**Decision:** a thin API client over a small runed backend store; no client-side state library.

**Files:** `src/lib/api/backend.svelte.ts`, `src/lib/api/client.ts`, `src/App.svelte`

### Backend lifecycle

`App.svelte` owns `backend.init()` and `backend.dispose()` in a single `onMount`. Every other component that needs the backend just reads `backend.ready` and waits. `ScriptsPanel` polls `backend.ready` for up to 15 seconds to accommodate late-arriving readiness, but it never calls `init` or `dispose` itself.

The store exposes `port`, `token`, `base`, `headers`, `ready`, `status`, and a `debug()` snapshot for the diagnostics panel. The token is never rendered into the DOM — `debug()` returns `tokenSet: boolean`, not the token.

### The API client is the only fetch path

Every backend call goes through `apiFetch` in `client.ts`. This is enforced by convention, not by types, but the audit is easy: search for `fetch(` under `src/lib/` and confirm every hit is in `client.ts` (or in `ScriptsPanel`'s diagnostic probes, which are explicitly bypassing the client for troubleshooting).

`apiFetch` handles: auth headers, debug logging, network-error message improvement, content-length-bounded response previews for the debug log, and `!res.ok` translation. Adding a new endpoint means adding one method to the `api` object, not writing another `fetch` call site.

### SSE

`readSSE` implements a minimal SSE reader over `fetch` streaming. It handles CRLF normalization, multi-line `data:` fields, and comment-line skipping (heartbeats). It yields `{event, data}` tuples.

`waitJob` is the higher-level API: it seeds with a `getJob` call (so mid-stream starts are safe), races the SSE stream against the timeout, falls back to polling on transport failure, and distinguishes user cancel from timeout.

### Runes over stores

The backend store uses `$state` directly rather than `writable()`. This is a small Svelte 5 idiom choice: runes compose better with `$derived` and avoid the `get(store)` ceremony. The lifecycle (`init`/`dispose`) is manual because there's exactly one backend per app instance.

### When to reconsider

- If a second backend is ever spawned (e.g., a per-channel sidecar), the singleton store becomes wrong.
- If `apiFetch` grows beyond ~100 lines, split out auth, logging, and error translation.
- If SSE ever needs bidirectional communication, move to WebSocket.

---

## 7. Release and packaging

**Decision:** PyInstaller **onefile**, signed _before_ `tauri build`, with `SIDECAR_PREBUILT=1` to skip the rebuild.

**Files:** `src-python/api_server.spec`, `scripts/build-sidecar.mjs`, `.github/workflows/release.yml`, `scripts/sign-sidecar.{sh,ps1}`

### Why onefile, not onedir

Tauri's `externalBin` bundles single files. Onedir mode requires a `_internal/` directory as a sibling of the executable, and Tauri places `resources/` in a different directory than the sidecar binary. In practice this fails at runtime with `Failed to load Python DLL '.../_internal/python312.dll'`.

Trade-offs of onefile, accepted deliberately:

- Cold start is 2–5 seconds (extracts to `%TEMP%` on every launch). The UI shows backend status meanwhile, so this is visible, not broken.
- Rust only knows the bootloader PID, not the real server PID. The shutdown design (§2) already handles this: `POST /shutdown` is primary, `kill()` is fallback.

**Do not enable UPX.** It's the number-one trigger for antivirus false positives on PyInstaller binaries.

### Signing

The sidecar is signed _before_ `tauri build`, not after. The reason: `tauri.conf.json`'s `beforeBuildCommand` runs `bun run build:sidecar`, which would rebuild the binary and clobber the signature. The release workflow does its own build, signs, then sets `SIDECAR_PREBUILT=1` so the `beforeBuildCommand` sees an existing binary and skips the rebuild.

The skip check in `build-sidecar.mjs` matches on the host triple. That means it only works when every matrix entry builds natively on its runner. A cross-compile entry would miss the guard and rebuild — wasted work, but no corruption (different filename). If a cross-compile entry is ever added, this check needs to become target-aware.

Both `sign-sidecar.sh` and `sign-sidecar.ps1` fail loudly if `SIGNING_REQUIRED=1` and no signing identity is configured. Never ship an unsigned sidecar; SmartScreen and Gatekeeper are the alternatives.

### Version sync

Five version sources: `package.json`, `tauri.conf.json`, `Cargo.toml`, `Cargo.lock`, and `pyproject.toml`. `scripts/sync-versions.mjs` updates the first four; `Cargo.lock` follows from `cargo check`. The release workflow validates all five before building.

If a sixth source is added, register it in the release workflow's version-check step. The comment there says exactly this.

### When to reconsider

- If a release asset is ever too large for GitHub, consider upx — _but only_ if you first verify no AV vendors flag it.
- If Intel macOS builds become a requirement, they need a self-hosted runner (GitHub has retired all Intel-hosted macOS images). The matrix has a commented-out entry showing what that would look like.

---

## 8. Decision summary

| Decision                                | Rationale                                            | Flip when                                              |
| --------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------ |
| One sidecar, spawned by Rust            | Simplicity; Tauri `externalBin` expects one binary   | Multiple sidecars needed                               |
| HTTP + bearer token over loopback       | WebView↔sidecar is direct, no Rust proxy             | Non-loopback binding needed                            |
| `READY <port>` on stdout                | Unambiguous handshake, works with OS-chosen ports    | Multiple sidecars                                      |
| In-process `JobManager`                 | Smallest correct pattern for a desktop app           | Job durability across restart needed, or multi-machine |
| SSE over `fetch` streaming              | `EventSource` can't send `Authorization`             | Bidirectional needed                                   |
| Heartbeats every 15s                    | Windows loopback proxies prune idle connections      | —                                                      |
| Cancel detaches waiter, not job         | Partial work stays cached; next run resumes          | —                                                      |
| Month-chunked Parquet cache             | Range shifts don't invalidate; coverage is trackable | Months too large, coverage logic bug-prone             |
| Coverage as interval list               | Handles partial fetches from upstream refusals       | Simplification if non-contiguous caching is dropped    |
| Immutability after next month           | Chat logs are append-only                            | Upstream ever allows edits                             |
| Eager Polars, one frame, fan-out        | Readable; per-module boundaries                      | Fused query plan would be 3×+ faster                   |
| `$state` over `writable()`              | Composition with `$derived`                          | Multiple backends                                      |
| Onefile PyInstaller                     | `externalBin` requires single-file bundling          | Tauri changes `externalBin` semantics                  |
| Sign before build, `SIDECAR_PREBUILT=1` | Preserves signature across build phases              | Cross-compile matrix entries                           |

---

## 9. What this document is not

- It is not a substitute for the code comments. Where the code explains _how_, this document explains _why_.
- It is not exhaustive. Any subsystem whose rationale is obvious from the code is left to the code.
- It is not stable. Any of these decisions should be revisited if the constraint that produced them changes.

If you change a decision, update this document in the same commit. A stale architecture doc is worse than none — it teaches the wrong reasoning.

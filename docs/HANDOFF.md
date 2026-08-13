# Handoff — 2026-08-12 (updated)

Written so the next session can pick up without re-deriving any of it. Facts
here were measured against the running system, not assumed.

## Where things run

| | |
|---|---|
| Downloader | `ubuntu-lab` = `100.115.177.3:30997` (tailscale), compose at `/srv/compose/oc-proxy-downloader/compose.yaml` (**needs `sudo -n`**) |
| VPN egress | `oc-proxy-vpn` — gluetun/Surfshark JP, HTTP proxy on `vpn:8888`, stack-internal only |
| oc-scraper (gayroms) | OCI box, reaches the downloader over tailscale |
| Repos | `oc-proxy-downloader`, `oc-scraper` — both on `main`, both pushed |
| Config volume | `/mnt/SSD-1TB-DOCKER/appdata/oc-proxy/config` — `downloads.db` lives here |
| Download volume | `/mnt/HDD-8TB-STRIPE/media3/game/switch/download` → `/downloads` |

Deploy is pull + recreate:

```
ssh ubuntu-lab
cd /srv/compose/oc-proxy-downloader
sudo -n docker compose pull oc-proxy-downloader && sudo -n docker compose up -d
```

**Never run two deploys concurrently** — they collide on the container name and
leave a half-renamed container behind.

Release flow: bump `backend/core/version.py` → merge to `main` → auto-tag
workflow builds the Docker image and the Windows EXE. Do not push tags by hand.

To read the database without fighting the running writer, snapshot it first:

```
D=/mnt/SSD-1TB-DOCKER/appdata/oc-proxy/config; T=/tmp/ocsnap
sudo -n rm -rf $T && sudo -n mkdir -p $T
for f in downloads.db downloads.db-wal downloads.db-shm; do sudo -n cp "$D/$f" $T/; done
sudo -n chmod -R a+r $T && sqlite3 $T/downloads.db "..."
```

## Done since the last handoff

**The backlog ran.** 1915 rows are `done` out of 1971. The connection-pool fix
(v2.16.2) held — the service stayed up through it.

**The permanently-failed rows were deleted.** 194 `dead`/`auth_required` rows
are gone; one `dead` row remains.

## Where the queue ended up (end of the v2.16.9 session)

```
done 1956   failed 8   stopped 0
```

The 8 remaining failures are not retryable — they are dead links or per-host
problems, listed at the end of this section. Everything below describes how the
queue got here.

## How the queue got there

Mid-session the count stood at 1930 `done` / 35 `failed` / 5 `stopped`. Those 51
failures broke down as below — kept because the *shape* of the breakdown is what
led to both bugs, not because the numbers are current (they are not; see the
final state above).

| count | what | verdict |
|---|---|---|
| 31 | `SSL/TLS 핸드셰이크 실패` on datanodes.to | fd exhaustion (#44). Sampled id 2218 on v2.16.8 with the limit raised: **done, 6.4 GB**. The rest should follow. |
| 6 | other transient parse/download blips | retry |
| ~~4~~ | ~~`HTTP 416`~~ | **fixed and resolved — see below** |
| 2 | 1fichier `검수 probe 404 (단발)` | needs a re-probe |
| 1 | `sqlite3.OperationalError: unable to open database file` | fd exhaustion (#44) — see open item 1 |
| 1 | Send.now `blocked` | one link |
| 1 | `dead` | leave it |

Retry via `POST /api/downloads/restart-failed-local` — but **read the list
first** (see the trap below). Rows carrying `서버 재시작으로 인한 초기화` were
in flight when a deploy recreated the container, not stopped by anyone; they
just need restarting.

By the time v2.16.8 shipped this had shifted: the SSL rows had been retried
away and the dominant failure was **24 rows of `캡차는 통과했으나 링크가
발급되지 않았습니다`, every one of them `use_proxy=1`**. See the egress section
— they were routed to an egress datanodes never serves. On v2.16.9 all 24 came
back `done`.

### The 8 that are left — none are retryable

| id | why |
|---|---|
| 1888, 1898, 1904 | 1fichier page returns 404 — link expired or file deleted |
| 1895, 1905 | 1fichier `검수 probe 404 (단발)` |
| 2032 | DataNodes confirms the file is gone |
| 2290 | parse timed out at 5 min (FlareSolverr) |
| 2401 | Send.now link could not be extracted |

Five are 1fichier 404s. Run `전체 링크 검수` on those before deciding they are
dead — a single 404 is not a verdict, which is what the `단발` marker records.

## The 416 bug (fixed in v2.16.5, completed in v2.16.6)

Four downloads — ids 2050, 2206, 2236, 2250 — sat permanently failed while
their finished file was already on disk. ~3.6 GB, complete, byte-for-byte.

The chain:

1. A server answered a `Range` request with **`200`**, not `206`. A 200 means
   "range ignored, here is the whole file from byte zero."
2. The code did not look at the status. It computed
   `total_size = Content-Length + initial_size`, inflating the total by exactly
   the bytes already on disk, and `download_file_content` opened the `.part` in
   append mode (`'ab'`).
3. `assert_downloaded_a_real_file` then compared a correct file against an
   inflated total, called it incomplete, and failed the row.
4. Every retry sent `Range: bytes=<full length>-`, which is past the end, and
   got a bare `HTTP 416`. Classified `unknown`. Stuck forever.

The arithmetic confirms it on all four rows: `total_size − .part size` is
exactly the resume offset, and the `.part` is exactly the resource length.
Row 2050 then proved it empirically — the re-downloaded file came out at
**484,635,681 bytes, byte-for-byte the size of the `.part` that was discarded**.

The fix lives in `backend/core/resume.py` (pure, 27 tests in
`backend/tests/test_resume.py`) and is wired into both download paths:

- **`effective_initial_size`** — only a `206` continues where we asked. A `200`
  restarts at byte zero, so the bytes on disk are overwritten, not appended to.
- **total_size supersede** — a body that starts at byte zero states the true
  length, so it overwrites a stale inflated total instead of being skipped.
  This self-heals rows that already carry a bad total.
- **`is_part_already_complete`** — a `416` carries the real length in
  `Content-Range: bytes */N` (RFC 7233). When that equals the `.part` size the
  download is finished: `_resolve_range_overrun` finalizes it without fetching
  a byte.
- **`probed_complete_length`** (v2.16.6) — **datanodes returns a bare 416 with
  no `Content-Range`.** Measured, not assumed: under v2.16.5 row 2050 took the
  "discard the `.part`" branch and re-downloaded 484 MB. RFC 7233 only
  *recommends* the header, so this is not an edge case for this hoster — it is
  the normal path. Now a
  one-byte `Range: bytes=0-0` probe settles it: a `206` states the length in
  `Content-Range`, a `200` means its `Content-Length` is the whole file. **The
  `.part` is deleted only once the length is known and disagrees**; when it
  stays unknown the row fails with the file left on disk.
- `HTTP 416` / `Range Not Satisfiable` now classify as `transient`, not
  `unknown`.

**Retrying those four rows finalizes them with no re-download** — but only
after the datanodes page re-parses (browser Turnstile, serialized one-at-a-time
per host), because the 416 only arrives once a fresh download link exists.

### Measured after v2.16.6 went live

The four `failed` rows were not the whole population — they were only the ones
that had come to rest. Rows still cycling were hitting the same 416 and silently
re-downloading. On v2.16.6:

```
416 완본 마무리: 9건        재다운로드 회피: 13.95 GiB        .part 삭제: 0건
```

Every probe came back `206` with the length. Grep the container log for
`완본 — 마무리만 수행` to re-count, and for `어긋남` to see whether a `.part`
was ever legitimately discarded (still zero).

All four original rows are `done`, each finalized at exactly its `.part` size,
with `total_size` self-corrected from the inflated value:

| id | total_size (was → now) | outcome |
|---|---|---|
| 2050 | 484,651,827 → 484,635,681 | re-downloaded 484 MB on v2.16.5 |
| 2206 | 2,362,232,012 → 2,349,835,240 | finalized, 0 bytes fetched |
| 2236 | 437,990,195 → 437,954,879 | finalized, 0 bytes fetched |
| 2250 | 619,393,843 → 619,347,432 | finalized, 0 bytes fetched |

**v2.16.5 shipped incomplete and cost the 484 MB in row 2050.** The
"`Content-Range` is only recommended" caveat was known when the code was
written, and the branch that deletes a good file on a missing header went out
anyway; it was caught from the production log, not before the deploy. When a
recovery path can delete data, the uncertain branch has to be closed *first*.

## Open items

### 1. A queued task holds a database connection

`_download_task` opens its session at the top and holds it for the whole
download, including while parked on a semaphore. Live sessions therefore track
*queued* items, not transferring ones. v2.16.2 removed the pool ceiling
(`NullPool`) so this no longer takes the app down, but the waste is real and
fixing it properly means restructuring the state machine.

One row (id 2369) died on `sqlite3.OperationalError: unable to open database
file` during the backlog run. This was first read here as a `NullPool`
connection-count consequence — **that reading was wrong**. #44 found the real
cause: the process ran with the default `RLIMIT_NOFILE` soft limit of 1024
(Docker's `ulimits` did not survive the entrypoint's `su`, so the shell showed
65536 while Python had 1024). SQLite reports fd exhaustion as `CANTOPEN`. Fixed
in v2.16.7 by raising soft to hard at startup. `NullPool` makes the app spend
more fds, so this item still matters — it is just not what killed row 2369.

### 2. ~~`commit()` then reading an ORM attribute~~ — resolved in v2.16.12

Fixed at the source instead of site by site: `SessionLocal` now sets
`expire_on_commit=False`, so a commit no longer marks every instance stale and
the following attribute read stops issuing a fresh SELECT.

Static count over the non-test tree: **85 `commit()` call sites, 42 of them
followed within six lines by a read of the row just written.** (The earlier
"233 sites" figure in this document counted something broader and was never
reproduced; 42 is what an AST pass actually finds.) The runtime saving is per
execution, not per site — a transfer that commits progress twenty times used to
pay twenty extra SELECTs.

**This is only safe because nothing leaned on the implicit refresh.** All seven
places that read `status == stopped` to notice a stop issued from *another*
session already called `db_async.refresh` first — checked one by one before the
change. Cancellation itself does not go through the database at all; it rides an
in-memory `threading.Event` in `core/cancel_signal.py`.

A second thing had to hold: **no column may be filled in by the database.** With
expiry off, an instance keeps what this session put in it, so a `server_default`
/ `onupdate` / trigger column would read as `None` forever instead of being
fetched on first access. There are none — all nine defaults are Python-side.

Without expiry, a forgotten refresh stops being a wasted query and becomes a
download that ignores the stop button, so `tests/test_expire_on_commit.py`
guards all of it: it measures that no SELECT follows a commit, that `refresh`
still re-reads, that no column is DB-populated, and — by AST — that every
stopped-check re-reads its row first. Both guards were verified against a real
violation: deleting one refresh made the AST guard name the line, and adding a
`server_default` column made the schema guard name it.

### 3. ~~The 12 leftover `.part` files~~ — resolved

All 12 were consumed by the 416 recovery and the egress retries. The download
directory now holds none. Disk: 1.4 T free of 7.2 T (82% used).

## Traps found the hard way

**Do not bulk-restart without reading the list first.** A blanket restart pulled
62 items including adult titles that then went through post-processing into the
public tinfoil shop. Cleaning that took deleting files in `roms/`, a leftover in
`roms_temp/`, and 8 database rows. Show the list, let the user choose.

**Verify layout against real rows.** Three grid breakages shipped in one session
and the user found every one in a screenshot; a harness with short placeholder
text had passed. Serve `frontend/dist` locally with `/api` proxied to the live
downloader, log in, and measure. `frontend/tests/layout.test.js` now covers the
structural cases and `npm test` gates every build, but it cannot see content
overflow.

**Sizes above ~512 GiB are page furniture.** Storage-plan badges ("2TB", "6TB")
used to beat the real file because the parser took the largest match in the raw
markup. Fixed in v2.11.0 for new parses; **rows parsed earlier keep their bogus
size until re-parsed**.

**A stored `total_size` is not evidence.** The 416 bug above is the second time
a wrong `total_size` produced a confident wrong verdict. When a row disagrees
with the file on disk, measure the file.

**The audit only judges hosts it can read.** It used to answer "1fichier URL 이
아님" for every other host with `definitive=True`, which overwrote the real
failure reason on 248 DataNodes rows. It now covers all supported hosts, with
markers read off live "file is gone" pages — except GoFile, whose HTML is a
JavaScript shell and is deliberately left undecidable.

## Egress routing

`download_route` (settings) — `manual` | `direct` | `vpn` | `auto` | `balance`.
It sat on `manual` for the whole life of the VPN sidecar, so **the VPN was never
used**. Now `balance`: take the egress with a free slot, preferring direct.

Host load does not increase. Slots are keyed `host@egress`, so each IP still
sees at most the site's own limit (DataNodes 3), the global ceiling of 8 still
applies, and retry spacing stays keyed by **host** (180s) so a second egress
does not shorten it.

Exit IPs: direct `58.236.176.166` (KR) vs VPN `193.148.16.118` (JP).

### That verification was not enough (v2.16.9)

Confirming the two egresses have different exit IPs says nothing about whether
a hoster will *serve* the second one. Measured per host, per egress:

| host | direct | VPN |
|---|---|---|
| datanodes.to | 1168 done / 2 failed | **0 done / 24 failed** |
| 1fichier.com | 743 done / 3 failed | 7 done / 2 failed |

**datanodes has never once succeeded over the VPN.** It solves the captcha and
then withholds the download link, so every attempt burned a browser captcha —
the most expensive, most serialized resource here — and held a host slot, to
reach a guaranteed failure. That is what the 24 `캡차는 통과했으나 링크가
발급되지 않았습니다` rows are; they are **not** the fd exhaustion #44 fixed
(retried on v2.16.8 with the limit raised, still failed).

`HOST_EGRESS_DENY` in `download_core.py` now records the standing denial, and
`_egress_blocked_for` honors it ahead of the learned table. It does not expire —
a learned block is about an exit IP going stale, this is hoster policy.

The VPN stays on for everything else. 1fichier works over it, and its per-IP
free-tier throttle is exactly what a second egress is good for. **When adding an
egress, measure the success rate per host, not the exit IP.**

## The Windows release (v2.16.10)

The pipeline was green but barely verified. `Verify EXE` only checked that a
file appeared on disk, which cannot see either way this build actually fails:

- **The EXE dies on launch.** v2.16.7 shipped `import resource` (Unix-only) and
  broke the Windows build. It was caught by luck — a test happened to import the
  module during collection. Nothing else would have noticed, and v2.16.7 has no
  release to this day.
- **The EXE comes up without its frontend.** `app_factory` only *warns* when the
  static bundle is missing and starts anyway, so an EXE with no UI inside passes
  every existence check and every backend health probe.

`standalone/smoke_test.ps1` now launches the real binary in the release job and
demands three things: `/api/auth/status` answers, `/` returns the app's
`index.html`, and the hashed `/assets/*.js` bundle that index references
actually serves. The third is what separates "index.html got bundled" from "the
whole dist directory got bundled".

The script's assertions were validated against the live app before shipping
(all three pass there), and its PowerShell parses clean. `DOCKER_CONTAINER=1`
is set only to suppress the browser auto-open — it is the app's existing switch
for that and touches nothing else; the frontend path keys on `sys.frozen`
first, so it cannot be misdirected by that variable.

### What it found on its first run

**Every Windows EXE released up to v2.16.10 was dead on arrival.**

```
ModuleNotFoundError: No module named 'passlib.handlers.bcrypt'
[PYI-7492:ERROR] Failed to execute script 'main' due to unhandled exception!
```

`core/auth.py` builds a `CryptContext(schemes=["bcrypt"])` at module scope.
passlib resolves a scheme name to a module at *runtime*
(`registry.get_crypt_handler` → `import passlib.handlers.<name>`), so
PyInstaller's static analysis never saw it and never bundled it. The build
passed, the file existed, the checksum was published, and the binary crashed
before serving a single request.

Nothing could have caught this without launching the EXE: the build machine has
passlib installed normally, so every test passes there.

Fixed in v2.16.11 by collecting the whole `passlib.handlers` package
(`collect_submodules`) rather than naming one module — the scheme is config, and
a second missing handler would fail identically.

**The lesson generalizes: any library that imports by name at runtime is
invisible to PyInstaller.** The app's own code has no dynamic imports (checked),
so the risk lives entirely in dependencies.

Not yet done: the Linux and macOS jobs still only build their archives. The same
launch test would suit them.

## Guards worth knowing about

- `backend/tests/test_event_loop_safety.py` — no async route handler, no writer
  function, and no sync helper called from async may touch the database on the
  event loop. Each rule was checked by re-introducing the bug it describes.
- `backend/tests/test_module_imports.py` — every module the EXE bundles must
  import. It found one that never could.
- `backend/tests/test_session_capacity.py` — 80 sessions at once, then serve a
  query through a fresh one.
- `backend/tests/test_resume.py` — the Range-resume rules above, written against
  the four stuck rows rather than a theory.
- `frontend/tests/layout.test.js` — column indexes, no flex on a `<td>`, phone
  scrolls sideways, sticky header.

Backend 907 tests, frontend 36. `npm test` runs in the Dockerfile and in all
three release jobs.

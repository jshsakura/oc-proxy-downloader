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

## What is left in the queue

51 rows are `failed`. They are not one problem:

| count | what | verdict |
|---|---|---|
| 31 | `SSL/TLS 핸드셰이크 실패` on datanodes.to | transient episode, not a bug — TLSv1.3 from the container is fine now. Retry them. |
| 6 | other transient parse/download blips | retry |
| 4 | `HTTP 416` | **was a real bug — fixed in v2.16.5, see below** |
| 2 | 1fichier `검수 probe 404 (단발)` | needs a re-probe |
| 1 | `sqlite3.OperationalError: unable to open database file` | see open item 2 |
| 1 | Send.now `blocked` | one link |
| 1 | `dead` | leave it |

Retry via `POST /api/downloads/restart-failed-local` — but **read the list
first** (see the trap below).

## The 416 bug (fixed in v2.16.5)

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
- **`probed_complete_length`** (v2.16.6) — RFC 7233 only *recommends*
  `Content-Range` on a 416. A server that omits it used to send us down the
  "discard the `.part`" branch, throwing away gigabytes on a guess. Now a
  one-byte `Range: bytes=0-0` probe settles it: a `206` states the length in
  `Content-Range`, a `200` means its `Content-Length` is the whole file. **The
  `.part` is deleted only once the length is known and disagrees**; when it
  stays unknown the row fails with the file left on disk.
- `HTTP 416` / `Range Not Satisfiable` now classify as `transient`, not
  `unknown`.

**Retrying those four rows finalizes them with no re-download** — but only
after the datanodes page re-parses (browser Turnstile, serialized one-at-a-time
per host), because the 416 only arrives once a fresh download link exists.

## Open items

### 1. A queued task holds a database connection

`_download_task` opens its session at the top and holds it for the whole
download, including while parked on a semaphore. Live sessions therefore track
*queued* items, not transferring ones. v2.16.2 removed the pool ceiling
(`NullPool`) so this no longer takes the app down, but the waste is real and
fixing it properly means restructuring the state machine.

One row (id 2369) died on `sqlite3.OperationalError: unable to open database
file` during the backlog run — the first observed consequence of holding that
many connections open at once under `NullPool`. One occurrence in ~2000 rows,
so it is a real but rare edge, and it is the same root cause as this item.

### 2. `commit()` then reading an ORM attribute — 233 sites

A commit expires the instance, so the next attribute read is a fresh SELECT.
Measured: one extra query per object. Fixed in the route layer and the bulk
handlers; the rest are unaudited. The AST guard cannot see them — they do not
start with `db.`.

### 3. The 12 leftover `.part` files

`ls /mnt/HDD-8TB-STRIPE/media3/game/switch/download/*.part` shows 12. Four are
the 416 rows above (real, complete, keep them until the retry finalizes them).
The rest are unaudited — check each against its row before deleting.

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

Verified: direct `58.236.176.166` (KR) vs VPN `193.148.16.118` (JP).

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

Backend 886 tests, frontend 36. `npm test` runs in the Dockerfile and in all
three release jobs.

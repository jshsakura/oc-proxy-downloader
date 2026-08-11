# Handoff — 2026-08-12

Written so the next session can pick up without re-deriving any of it. Facts
here were measured against the running system, not assumed.

## Where things run

| | |
|---|---|
| Downloader | `ubuntu-lab` = `100.115.177.3:30997` (tailscale), compose at `/srv/compose/oc-proxy-downloader/compose.yaml` (**needs `sudo -n`**) |
| VPN egress | `oc-proxy-vpn` — gluetun/Surfshark JP, HTTP proxy on `vpn:8888`, stack-internal only |
| oc-scraper (gayroms) | OCI box, reaches the downloader over tailscale |
| Repos | `oc-proxy-downloader`, `oc-scraper` — both on `main`, both pushed |

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

## Open items

### 1. Run the backlog — blocked on deploying v2.16.2

65 rows are retryable (59 DataNodes, 5 1fichier, 1 Send.now). Their sizes total
"2.3 TB" but **one row is a mis-parsed 2.00 TiB** (id 1931, a storage-plan badge
scraped as a file size); the real payload is **≈105 GB** against 1.4 TB free.

Starting them on ≤ v2.16.1 takes the service down — see the connection-pool
note below. v2.16.2 fixes it. Sequence: deploy 2.16.2, then
`POST /api/downloads/restart-failed-local`, then watch `/api/auth/status`
latency while it ramps.

### 2. Delete the permanently-failed rows

194 rows are `dead`/`auth_required`. The audit confirmed these — 189 DataNodes
`dead` verdicts were re-probed and every one returned a real 404. Error-type
classification was checked across all 257 rows carrying a message: **no message
names a hoster other than the row's own**. Safe to delete via
`POST /api/downloads/bulk-delete`.

### 3. A queued task holds a database connection

`_download_task` opens its session at the top and holds it for the whole
download, including while parked on a semaphore. Live sessions therefore track
*queued* items, not transferring ones. v2.16.2 removed the pool ceiling
(`NullPool`) so this no longer takes the app down, but the waste is real and
fixing it properly means restructuring the state machine.

### 4. `commit()` then reading an ORM attribute — 233 sites

A commit expires the instance, so the next attribute read is a fresh SELECT.
Measured: one extra query per object. Fixed in the route layer and the bulk
handlers; the rest are unaudited. The AST guard cannot see them — they do not
start with `db.`.

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
- `frontend/tests/layout.test.js` — column indexes, no flex on a `<td>`, phone
  scrolls sideways, sticky header.

Backend 839 tests, frontend 36. `npm test` runs in the Dockerfile and in all
three release jobs.

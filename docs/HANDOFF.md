# Handoff

Current state for the next session. For the history of how each host behaves, see
[HOSTER_CASES.md](HOSTER_CASES.md); for the user-facing summary, see the
[README](../readme.md). The detailed August 2026 incident record that used to live here
is in git history (`git log -- docs/HANDOFF.md`).

## State

- Version in the tree: `v2.16.94` (`backend/core/version.py`). The last tag is `2.16.92`.
- The working tree holds uncommitted work for v2.16.93 and v2.16.94, catalogued in
  HOSTER_CASES.md, plus `backend/tests/test_download_fix_regressions.py`. These
  sources are included in the local deployment below but have not been released
  through the registry. Run the backend tests before committing further changes.
- On 2026-10-31, the running service was rebuilt from this working tree as
  `oc-proxy-downloader:2.16.94-settings-ui-20261031` and pinned in
  `<compose stack>/compose.yaml` (`pull_policy: never`). All live
  backend Python sources matched the working tree before deployment; this image
  preserves those fixes and includes the TeraBox account UI grouped like 1fichier.
  Frontend: 147 tests passed. Backend in the new Python 3.11 image: 1,478 passed,
  1 skipped. Authenticated live desktop/mobile UI checks passed. The 2,395 completed
  download records were preserved; no downloads were active during deployment.
- Deployment sources, image manifest, compose backup, readiness-aware deploy script,
  and previous frontend/locales are in
  `<compose stack>/settings-ui-20261031/`. The rollback image is
  `oc-proxy-downloader:rollback-settings-ui-20261031`; use that directory's
  `compose.rollback.yaml` with the original compose project directory to restore it.
  This is a local deployment; no release tag or registry image was published.
- Earlier follow-up on 2026-10-31: production then pinned
  `oc-proxy-downloader:2.16.94-qr-platform-20261031`. This locale-only image adds
  the Android-only/iOS-unsupported QR guidance present in the imported NX UI but
  omitted from our settings. Its build context and rollback compose are in
  `<compose stack>/qr-platform-20261031/`; rollback uses the
  preceding settings UI image. See [TERABOX_QR_LOGIN.md](TERABOX_QR_LOGIN.md) for
  source locations and the actual official/production QR comparison. Do not
  claim the QR flow supports iPhone scanning or that live account approval was
  verified by the UI tests.
- Earlier design follow-up: production then pinned
  `oc-proxy-downloader:2.16.94-account-ui-20261031`. Both account services use
  matching icon/status cards. TeraBox has keyboard-accessible email/QR/cookie
  tabs, an Android QR guide, and an iPhone cookie shortcut. Switching methods
  preserves inputs and cancels pending QR polling. The image changes only
  frontend assets and locale files. Frontend tests: 147 passed; mocked QR
  lifecycle and saved-account checks passed at 320/390/1100 px in Korean/English
  and light/dark themes. Authenticated production desktop/mobile checks passed.
  Build inputs, source snapshot, manifest, readiness-aware deploy script and
  rollback Compose file are in
  `<compose stack>/account-ui-20261031/`; rollback uses the
  preceding QR-platform image. No active downloads were restarted.
- Current deployment: production pins
  `oc-proxy-downloader:2.16.94-host-refusal-r4-20261108`. It is r3 plus one fix.
  A file that fails with `auth_required` (Rapidgator over 500 MB on a free account,
  a password, a missing permission) no longer puts its whole host on a one-hour
  wait. Build inputs and rollback Compose are in
  `<compose stack>/host-refusal-r4-20261108/`.
- Previous deployment: production pinned
  `oc-proxy-downloader:2.16.94-terabox-qr-region-r3-20261101`, which adds multi-file
  shares, regional hosts and the in-app scanner wording, with build inputs in
  `<compose stack>/terabox-qr-region-r3-20261101/`. With a saved cookie, TeraBox
  shares download from the fastest SDK server (`core/terabox_sdk.py`). Measurements
  and limits are in [TERABOX_QR_LOGIN.md](TERABOX_QR_LOGIN.md). QR sign-in is still
  unverified on a real phone and needs the scanner inside the app; the phone's
  camera only opens the website. Build inputs, source snapshot, guarded deploy script
  and rollback Compose are in `<compose stack>/terabox-sdk-r2-20261031/`.
- Earlier repair deployment: production pinned
  `oc-proxy-downloader:2.16.94-terabox-repair-20261031`. TeraBox now offers
  cookie and QR only. Retired email/password keys are removed from persisted
  settings and rejected from stale clients; the verified session cookie was
  retained. The missing ndus cookie on file requests caused real HTTP 403 /
  error 31045; the repair carries it in a secure, domain-scoped cookie jar
  through the file-server redirect. An actual aiohttp Range request returned
  HTTP 206 and binary data. Only failed request 2954 was retried after clearing
  its exact historical authentication cooldown. At 12:53 KST it was downloading
  with 49,405,952 bytes on disk, total 5,010,096,128, and no error; completion has
  not been verified. Do not restart or recreate this service while it transfers.
  Backend: 1,483 passed, 1 skipped. Frontend: 147 passed. Authenticated production
  settings, desktop/mobile layout, two login methods and the white QR surround
  passed browser checks. QR requests now match the observed official canonical
  origin/context; actual generation and waiting_scan passed, but Android phone
  approval has not been observed. See [TERABOX_QR_LOGIN.md](TERABOX_QR_LOGIN.md).
  Build inputs, source snapshot, manifest, guarded deploy script and rollback
  Compose are in `<compose stack>/terabox-repair-20261031/`.
  The final white QR surround was copied into the running container and baked
  into the same image tag without restarting the active transfer. The manifest
  records both image IDs; do not recreate merely to align them. Rollback points
  to the preceding account UI image. No release tag or registry push was made.

## Where things run

- The downloader runs as a Docker container (app plus FlareSolverr). It needs a real
  browser and Xvfb, which exist only in the Docker image.
- A VPN sidecar provides a second egress. `download_route` in settings selects
  `manual`, `direct`, `vpn`, `auto` or `balance`.
- Config and the SQLite database live in the mounted config volume; downloads in the
  mounted downloads volume. Deployment is a pull and recreate of the compose stack on
  the server. Never run two deploys at once: they collide on the container name.
- Release flow: bump `backend/core/version.py`, merge to `main`, and the auto-tag
  workflow builds the Docker image and the Windows EXE. Do not push tags by hand.
- To read the database without fighting the running writer, copy `downloads.db`
  together with its `-wal` and `-shm` files first and query the copy.

## Open items

- TeraBox: QR approval on a real phone still needs a device result; the user
  reports failure on Android. A generated QR and waiting_scan are insufficient
  evidence. Polls now log step and code. The Android-only label was AI-written, not
  a TeraBox restriction, and was removed.
  Settings support only `terabox_ndus` (manual cookie or approved QR). Do not
  restore retired email/password login as a workaround. Multi-file shares split
  into one row per file, and `?pwd=` access codes remain supported.
- A queued task still holds a database connection while it waits on a semaphore
  (`_download_task`). `NullPool` keeps this from taking the app down, but fixing it
  properly means restructuring the state machine.
- The Linux and macOS release jobs only build their archives. The launch smoke test
  that the Windows job runs would suit them too.
- Sizes above about 512 GiB are page furniture (storage-plan badges). Rows parsed
  before v2.11.0 keep a bogus size until they are parsed again.

## Traps found the hard way

- **Do not bulk-restart without reading the list first.** A blanket restart once pulled
  in items that then went through post-processing into a public shop. Show the list and
  let the user choose.
- **A stored `total_size` is not evidence.** Twice a wrong value produced a confident
  wrong verdict. When a row disagrees with the file on disk, measure the file.
- **Resume deletes data if the uncertain branch is open.** The Range-resume rules in
  `core/resume.py` and `tests/test_resume.py` were written against real stuck rows. A
  missing `Content-Range` must never delete a good `.part`.
- **File descriptors.** The process once ran with a soft limit of 1024 because Docker's
  `ulimits` did not survive the entrypoint's `su`. SQLite reports fd exhaustion as
  `unable to open database file`. Startup now raises the soft limit to the hard one.
- **Egress per host.** Different exit IPs say nothing about whether a hoster serves the
  second one. DataNodes never succeeded over the VPN, so `HOST_EGRESS_DENY` in
  `download_core.py` records that standing denial. When adding an egress, measure the
  success rate per host.
- **Anything imported by name at runtime is invisible to PyInstaller.** `passlib`
  handlers were missing from every Windows EXE until v2.16.11. The release job now
  launches the real binary (`standalone/smoke_test.ps1`).
- **Diagnostic runs spend host quota.** Probing Rapidgator or 1fichier to a link
  issuance uses the same limit a real download would.
- **Layout needs real rows.** Short placeholder text hides grid breakage. Serve
  `frontend/dist` against the live API and measure.

## Guards worth knowing about

- `backend/tests/test_event_loop_safety.py`: no async route handler, writer or sync
  helper called from async may touch the database on the event loop.
- `backend/tests/test_module_imports.py`: every module the EXE bundles must import.
- `backend/tests/test_session_capacity.py`: 80 sessions at once, then a query through
  a fresh one.
- `backend/tests/test_resume.py`: the Range-resume rules.
- `frontend/tests/layout.test.js`: column indexes, no flex on a `<td>`, phone scrolls
  sideways, sticky header.

`npm test` runs in the Dockerfile and in all three release jobs.

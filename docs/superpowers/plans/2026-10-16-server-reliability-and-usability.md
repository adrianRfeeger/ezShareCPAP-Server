# Server reliability and usability implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, or superpowers:subagent-driven-development if the owner selects that execution method. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server easier to understand, recover and maintain by adding storage management, clearer sync status, stop/resume controls, scheduling feedback, share shortcuts and connection diagnostics.

**Architecture:** Keep the existing Flask/Waitress interface, Docker Compose services, file-backed state and single-sync lock. Add focused storage, run-control, scheduling and diagnostics helpers; preserve atomic file writes and publication of complete snapshots. Wi-Fi information comes from an optional read-only collector in the Linux guest, where the interface is available.

**Tech stack:** Python, Flask, Waitress, vanilla JavaScript modules, pytest, Node's test runner, Docker Compose, Samba and optional systemd guest services. No frontend framework or database is required.

**Spec:** [Design brief in this document](#design-brief). This plan implements the six improvements discussed with the owner. Defaults below are proposals for implementation, not settings already applied to the live server.

**Source baseline:** `1b44ee0`, repository `adrianRfeeger/ezShareCPAP-Server`, local checkout `/Users/adrianfeeger/Development/Python/ezShareCPAP-Server`. The original desktop repository is outside this work.

## Design brief

The server should explain what it has, what it is doing and when its files are ready for OSCAR. A seeded file is available in the working archive immediately, but it becomes shareable only after a successful sync publishes a snapshot. The dashboard must make that distinction clear.

The owner should be able to stop after a file completes, resume using the existing cache, see the next scheduled run in the configured timezone, and connect to the SMB share without editing a script. Storage use and connection failures should be visible before they interrupt daily use.

Deliver six stages, in this order:

1. Storage reporting, space checks and snapshot retention.
2. First-sync, seed and publication status.
3. Stop/resume and restart recovery.
4. Schedule preview, snapshot age and failure warnings.
5. Configurable SMB address and Open in Finder link.
6. Card connectivity, Wi-Fi information and transfer diagnostics.

Each stage should be independently testable and deployable. Stage 1 introduces resource coordination used by later stages. Stages 2 and 3 establish the state model used by scheduling and diagnostics. Stage 5 can be implemented independently after the common settings validation is established.

### Proposed defaults and behaviour

| Area | Proposed behaviour |
| --- | --- |
| Retention | Keep the latest two completed snapshots when enabled. Existing and new configurations leave automatic deletion disabled until the owner enables it after seeing a preview. |
| Storage reserve | Leave at least 1 GiB free for server operations. Warn below the greater of 2 GiB or 15% of filesystem capacity. |
| Snapshot publication | Check that a full independent copy plus reserve fits before copying. Never replace `current` with an incomplete snapshot. |
| First-sync copy | “Local files imported. The network share will be ready after the first sync completes.” |
| Stop | Finish the current file, then stop before starting another. During scanning or verification, stop between requests. During publication, abandon staging and keep the previous snapshot. |
| Resume | Start a fresh scan and reuse complete cached files. Restart a partial file from the beginning. |
| Restart recovery | Resume interrupted runs automatically by default, once per startup, while respecting a saved user pause. An active process holding the sync lock takes precedence. |
| Time limits | Preserve the existing 30-minute normal limit. Add a configurable initial-sync limit, proposed 24 hours, whenever no completed snapshot exists. |
| Scheduling | Keep daily wall-clock scheduling, catch up once after a missed time and retain the existing daylight-saving policy. Show times in the configured timezone, initially Australia/Melbourne. |
| Warnings | Warn after two consecutive failed scheduled runs, or when the latest successful snapshot is more than 36 hours old. Show “No completed snapshot yet” separately. |
| SMB | Keep `CPAP` and `cpap` consistent with Samba. Add an optional SMB hostname/IP setting; otherwise use the dashboard hostname. |
| Diagnostics | Use transfer activity while syncing. Permit a bounded card check while idle. Optional guest Wi-Fi samples every 15 seconds become stale after 60 seconds. |

The retention count is intentionally small because the current guest was provisioned with a 16 GiB disk and snapshots are full copies. Before deployment, measure actual free space and archive size. Do not assume the proposed count guarantees enough room for upload staging, export preparation and the next snapshot.

### Boundaries

This work does not change therapy files, OSCAR profiles, Wi-Fi transmit power or the server's network permissions. It does not expose working files through SMB or publish an imported ZIP directly as a verified snapshot. Notifications mean dashboard warnings in this release; email, push services and Windows/Linux connection scripts are separate features.

## Global constraints

- Work in the standalone server repository and preserve unrelated changes. Use an isolated branch/worktree for implementation, following the owner's established preference.
- Keep web authentication, CSRF protection and same-origin checks on every state-changing endpoint.
- Keep the downloader unprivileged with a read-only root filesystem, dropped capabilities and no Docker socket.
- Keep Samba read-only and preserve existing credentials. Never include passwords in scripts, URLs, diagnostics or logs.
- Preserve complete cached files, case-insensitive path reuse, ZIP timestamp normalization and device identity checks.
- Completed snapshots remain independent copies. Do not introduce hard links from the mutable working archive.
- Store machine timestamps in UTC; format user-facing dates with the configured IANA timezone.
- Reject invalid settings before replacing the current configuration; old configurations remain loadable.
- Existing clients of `/api/status` must continue to work while fields are added. New JavaScript must tolerate missing fields during upgrades.
- Do not scan the entire archive or probe the card on every two-second status request.
- Only intentional retention actions may remove completed snapshots. Never delete the working archive, the current target, symlink targets outside the publication directory or unknown directories.

## Source map

| File | Responsibility or planned change |
| --- | --- |
| `server.py` | Configuration validation, orchestration, state, publication, scheduler and health. Integrate helpers without rewriting unrelated desktop behaviour. |
| `storage.py` (new) | Storage inventory, retention preview/application, publication locking and capacity reservations. |
| `run_control.py` (new) | Run-scoped stop requests, persistent pause and restart recovery decisions. |
| `scheduling.py` (new) | Shared daily scheduling decisions and next-run calculation. |
| `diagnostics.py` (new) | Parse optional Wi-Fi samples and derive bounded card/transfer diagnostics. |
| `webapp.py` | Settings and control endpoints, additive status fields and SMB URL generation. |
| `archive_io.py` | Coordinate import/export space and snapshot readers with storage management. |
| `ezshare.py`, `file_ops.py` | File-boundary stop checks, inventory counters and transfer telemetry. |
| `templates/index.html`, `static/progress.js`, `static/style.css` | Dashboard sections and controls. |
| `static/status-view.mjs` (new) | Pure formatting and state-to-label functions that can be tested without a browser. |
| `static/imports.js`, `static/eta.mjs` | Update only where new state affects existing upload or ETA behaviour. |
| `scripts/collect_wifi_status.py` (new) | Optional guest-side collector with fixed commands and atomic JSON output. |
| `docker/systemd/ezshare-wifi-status.service`, `.timer` (new) | Optional installation in CT 114, not the Proxmox host. |
| `compose.yaml`, `Dockerfile` | Package helper modules and optionally mount a read-only diagnostics directory. |
| `tests/test_storage.py`, `test_run_control.py`, `test_scheduling.py`, `test_diagnostics.py`, `test_status_view.mjs` (new) | Focused behavioural coverage. Extend existing server, archive, web and integration tests. |
| `docs/docker-deployment.md`, `docs/proxmox-deployment-record.md`, `README.md` | Setup, migration, operational behaviour and verified deployment evidence. |

## Review focus

1. A ZIP export and retention cleanup run together: the selected snapshot must remain readable until ZIP preparation finishes. Covered in task 1.
2. A long upload, sync and publication compete for the same disk: reserve checks must account for concurrent operations and preserve completed data on ENOSPC. Covered in task 1.
3. Stop, resume and container shutdown cross process boundaries: stale requests must not stop a new run, and a user pause must survive restart. Covered in task 3.
4. Melbourne's repeated or missing daylight-saving times and scheduler catch-up must match the time shown on the page. Covered in task 4.
5. Proxied dashboard addresses, IPv6, missing Wi-Fi tooling and stale samples must produce safe, understandable results. Covered in tasks 5 and 6.

## Task 1: Manage storage and snapshot retention

**Files:** Create `storage.py`, `tests/test_storage.py`; modify `server.py`, `archive_io.py`, `webapp.py`, `templates/index.html`, `static/progress.js`, `Dockerfile`, deployment documentation and affected integration tests.

**Interfaces:**

- `storage_status(root: Path) -> dict`: cached category sizes plus fresh filesystem free/total bytes, reserved bytes, scan timestamp and warning.
- `retention_preview(root: Path, keep: int) -> dict`: recognised snapshots to retain/delete, reclaimable bytes and protected current target.
- `prune_snapshots(root: Path, keep: int) -> dict`: revalidate and remove only eligible snapshots while holding the publication lock.
- `snapshot_access(root: Path, exclusive: bool)`: shared/exclusive cross-process context manager for export readers versus publication/retention.
- `reserve_space(root: Path, operation: str, required_bytes: int, reserve_bytes: int)`: context manager returning a reservation handle with `consume(bytes_written: int)`; atomically accounts for outstanding commitments, releases on exit and recovers dead-owner reservations.
- Configuration: `retention_enabled=false`, `retention_keep=2` (integer 1..10), `storage_reserve_bytes=1073741824` (integer at least 268435456).
- Status: `storage={free_bytes,total_bytes,work_bytes,snapshot_bytes,temp_bytes,reserved_bytes,updated_at,warning}`.

- [ ] Add failing tests for the following behaviours: with four completed snapshots and keep=2, only the oldest two are eligible; a failed new sync leaves every completed snapshot intact; `current`, external symlinks and unrelated directories are never deleted; invalid/missing current targets prevent automatic pruning.
- [ ] Add concurrency tests showing that an export holds a shared publication lock until its ZIP is complete and cleanup waits; requests exceeding free space minus outstanding reservations and the 1 GiB reserve fail before destructive work. Test that reservation consumption does not double-count bytes already written, a dead owner is recoverable, and ENOSPC during copying leaves the prior snapshot intact.
- [ ] Run `python -m pytest tests/test_storage.py tests/test_archive_io.py tests/test_server.py -q` and confirm the new cases fail for missing behaviour.
- [ ] Implement inventory and reservations. Keep reservation records behind a short-lived file lock and an owner-held lease so a crashed process cannot reserve space forever. Update archive/category totals after file operations, with a background refresh at most once per 60 seconds. Use filesystem free-space checks during chunked writes as a final guard against unrelated disk use.
- [ ] Apply reservations to ZIP request-body spooling, saved uploads, extraction, snapshot copies and ZIP exports. Inspect Waitress's buffering lifecycle: the request body may be spooled before Flask runs. Make the upload path admit declared lengths before unbounded spooling, or use a dedicated streaming upload endpoint; reject oversized and unsupported unknown-length upload bodies. Test this against the actual HTTP server, not only Flask's client. Budget simultaneously existing spool, saved ZIP and extraction bytes.
- [ ] Integrate snapshot locks. Preserve the existing nonblocking sync and transfer locks. Acquire locks in this order when needed: transfer, sync, publication; reservation metadata locks are brief and never held while waiting for another lock. Sync publication uses sync then publication. Export uses transfer then shared publication. Manual cleanup uses sync then exclusive publication. Never require a transfer lock from a running sync.
- [ ] After successful publication, prune only when enabled; a pruning failure becomes a storage warning rather than converting a successful sync into a failed download. When space is insufficient before publication, leave all snapshots intact and offer a retention preview, more storage or a smaller retention count.
- [ ] Add storage display, retention settings and authenticated CSRF-protected `POST /storage/prune`. Enabling retention shows the count and deletion preview. Manual cleanup takes an exclusive publication lock and re-evaluates eligibility; return 409 if sync is active. Explain that dated snapshots outside the retained set expire and should not be imported while cleanup is requested.
- [ ] Run the focused tests and an HTTP upload with limited test storage; expect clean rejection, no corrupted current snapshot and no abandoned reservation. Document how small disks constrain the nominal 4 GB upload limit.
- [ ] Commit the independently working storage stage with its documentation.

## Task 2: Explain seeded files and first publication

**Files:** Modify `server.py`, `archive_io.py`, `ezshare.py`, `file_ops.py`, `templates/index.html`, `static/progress.js`, `static/imports.js`; create `static/status-view.mjs` and `tests/test_status_view.mjs`; extend `tests/test_progress.py` and `tests/test_webapp.py`.

**Interfaces:**

- Add `archive={working_files,last_import_added,last_import_kept,last_import_at,published_files,published_at}` to status. `last_import_*` describes the last import operation, not a permanent count of all seeded files.
- Add `progress.inventory={card_files,reused_files,download_required,downloaded,remaining}`. Unknown counts are `null`; planning determines counts from the card manifest, not by adding potentially overlapping import/download totals.
- Add `availability` with `empty`, `seeded_pending`, `first_sync`, `ready`, `ready_syncing` or `interrupted_pending`. Actual published snapshot availability takes precedence over old import state.
- `status-view.mjs`: `availabilityMessage(state) -> string` and `formatTimestamp(value, timezone) -> string`.

- [ ] Add failing state tests for an empty installation, imported-but-unpublished files, active first sync, retry after partial download, published seeded files and failure with a previous completed snapshot. Confirm remaining is never negative and is unknown before planning.
- [ ] Add JavaScript tests asserting the exact seeded-pending message from the design brief, a published snapshot remains labelled available during a subsequent failure, and missing fields produce readable fallback text.
- [ ] Run `python -m pytest tests/test_progress.py tests/test_webapp.py -q` and `node --test tests/test_status_view.mjs`; confirm the new tests fail.
- [ ] Persist import totals/timestamp and derive archive totals during existing operations. Count reuse and required downloads with the same timestamp, size and case-matching rules used by the downloader. Reset per-attempt counters on retry while retaining the working archive.
- [ ] Add an “Available for OSCAR” status beside the share/download controls. Display last import additions separately from current-run downloaded/remaining counts. Clear the active error at run start and retain previous errors in history, avoiding an old failure beside a new healthy run.
- [ ] Verify the focused tests and inspect the rendered page in empty, seeded, running and ready states. Confirm polling preserves unsaved schedule fields and does not shift the form on every update.
- [ ] Commit the status stage and its documentation.

## Task 3: Stop, resume and recover interrupted runs

**Files:** Create `run_control.py`, `tests/test_run_control.py`; modify `server.py`, `ezshare.py`, `file_ops.py`, `webapp.py`, `templates/index.html`, `static/progress.js`, `Dockerfile` and server integration tests.

**Interfaces:**

- `request_stop(root: Path, run_id: str) -> dict`: atomically record a stop for the named active run and persist a user pause.
- `stop_requested(root: Path, run_id: str) -> bool`: ignore stale requests from another run.
- `recovery_decision(root: Path, status: dict, cfg: dict) -> str`: `none`, `resume` or `paused`, evaluated with the sync lock held.
- `POST /sync/stop`: authenticated CSRF-protected request with run ID; 409 for a different active run, idempotent for the same pending request.
- `POST /sync/resume`: authenticated CSRF-protected request; clear the user pause only once the new run is admitted, never start a second worker.
- Status: `run_state` of `idle`, `running`, `stop_requested`, `paused`, `interrupted`, `recovering`, `failed` or `completed`, with `resume_available`.
- Configuration: `resume_interrupted=true`, `initial_sync_timeout=86400` (integer 1..86400). Preserve the existing `timeout` for installations with a completed snapshot.

- [ ] Write failing tests for stop during a file transfer, scanning, retry delay and publication. Assert complete cached files survive, partial files never enter a snapshot, no second file starts after stop, and the previous `current` target survives an abandoned publication.
- [ ] Add process-level tests for simultaneous stop/resume clicks, a stale run ID, a user pause surviving restart, a crashed run resuming once, and an already-held sync lock blocking recovery. Assert resume and a due schedule cannot create two sequential duplicate startup runs.
- [ ] Run `python -m pytest tests/test_run_control.py tests/test_server_integration.py tests/test_server_downloads.py -q`; confirm the new tests fail.
- [ ] Implement a persistent run-scoped control file. Keep service shutdown (`STOP`) distinct from user pause. Check user stop before each request/file and after atomic file completion. During a file, allow its bounded transfer to finish; add an absolute per-file deadline of 300 seconds alongside existing socket timeouts so a trickling connection cannot hold stop indefinitely. Delete only that unfinished temporary file if the deadline expires.
- [ ] Record intentional stops as `Stopped`, not `Failed`, and skip retries after a user stop. Resume rescans the card and reuses cached files. A pause suppresses scheduled runs until Resume is chosen, with this consequence stated beside the control.
- [ ] Recover interrupted runs once during service startup, independent of `run_on_startup`, using the configured initial or normal timeout. Persist sufficient intent to distinguish paused, interrupted and completed work. Leave exhausted failures idle until the next schedule or manual request, avoiding restart loops.
- [ ] Add Stop/Resume controls and “Stopping after the current file” feedback. Disable incompatible import/sync actions using the shared busy state, including during recovery.
- [ ] Run focused tests plus a synthetic child-process interruption test. During deployment, retire the temporary initial-sync container only after it has finished or stopped safely, then hand future recovery to the normal Compose service. Never start both recovery mechanisms together.
- [ ] Commit recovery changes with the updated operations guide.

## Task 4: Show the next run and stale-data warnings

**Files:** Create `scheduling.py`, `tests/test_scheduling.py`; modify `server.py`, `webapp.py`, `static/status-view.mjs`, `static/progress.js`, `templates/index.html` and existing scheduling tests.

**Interfaces:**

- `schedule_decision(now: datetime, cfg: dict, last_scheduled_date: str | None) -> dict` returns `due_date` and `next_run_at` as an aware UTC datetime.
- `schedule_status(now: datetime, cfg: dict, status: dict) -> dict` returns `next_run_at`, `timezone`, `paused`, `overdue`, `snapshot_age_seconds`, `consecutive_scheduled_failures` and `warnings`.
- Add `trigger` (`manual`, `scheduled`, `recovery`) and `schedule_date` to future history records. Legacy records have unknown trigger and do not count as proven scheduled failures.

- [ ] Add failing tests for the Melbourne spring gap on 2026-10-04, repeated hour on 2026-04-05, normal dates, a missed day, schedule edits, a paused run and a due time while busy. The displayed due decision must agree with the scheduler.
- [ ] Add tests that two scheduled failures trigger a warning, a manual failure alone does not, a scheduled success clears the consecutive-failure warning, and a snapshot older than 129600 seconds gets an age warning. Missing success time uses first-sync wording.
- [ ] Run `python -m pytest tests/test_scheduling.py tests/test_server.py -q`; confirm the new cases fail.
- [ ] Extract the existing daily policy into the shared helper. For a missing local time, run at the first valid minute after the gap; for a repeated local time, run once per saved local date. Catch up once, not once per missed day. If busy, expose “Due; waiting for current operation” and keep the date eligible until admitted.
- [ ] Add next-run, last-success age and warnings to the API and page. Format history and timestamps in the configured timezone with a visible timezone label; retain UTC storage. Preview unsaved schedule changes separately from the saved next-run value.
- [ ] Run focused Python and JavaScript tests and inspect rendered normal, paused, overdue and failure states. Verify warning text does not imply all failures are network failures.
- [ ] Commit the scheduling stage and documentation.

## Task 5: Simplify SMB access and support an explicit host

**Files:** Modify `server.py`, `webapp.py`, `templates/index.html`, `tests/test_webapp.py`, `docs/docker-deployment.md` and `README.md`.

**Interfaces:**

- Configuration: `smb_host=""`, meaning use the dashboard hostname. Accept only a DNS hostname, IPv4 address or IPv6 address; reject scheme, credentials, port, path, query, whitespace and shell metacharacters.
- `smb_url(configured_host: str, request_host: str) -> str` returns a validated `smb://cpap@host/CPAP` URL with IPv6 brackets where needed.
- Both the existing `/connect-mac.zip` generator and the new “Open in Finder” anchor use this helper. Share/user remain fixed to match Samba.

- [ ] Add failing tests proving an explicit LAN host overrides a proxied dashboard host, fallback removes the web port, IPv6 works, unsafe values are rejected and generated ZIPs remain executable without containing a password.
- [ ] Run `python -m pytest tests/test_webapp.py -q`; confirm the new cases fail.
- [ ] Add the validated setting and common URL builder. Add “Open in Finder”, a readable share address and the existing script download beside each other. Explain that a saved script keeps the address from when it was downloaded and can be downloaded again after an address change.
- [ ] Review the current Content Security Policy against browser handling of an `smb:` link. Verify in a real browser and allow only the precise necessary behaviour; do not broadly weaken the policy. Preserve the downloadable script as a fallback when the browser requires confirmation or blocks external protocols.
- [ ] Verify the tests, download and inspect a live ZIP, and exercise Finder connection with the owner entering credentials if requested. Confirm the share shows the same completed snapshot as the dashboard.
- [ ] Commit the share-access stage and documentation.

## Task 6: Add useful connection diagnostics

**Files:** Create `diagnostics.py`, `scripts/collect_wifi_status.py`, `docker/systemd/ezshare-wifi-status.service`, `docker/systemd/ezshare-wifi-status.timer`, `tests/test_diagnostics.py`; modify telemetry in `ezshare.py` and `file_ops.py`, status in `server.py`, routes in `webapp.py`, dashboard assets, `Dockerfile`, optional Compose diagnostics configuration and deployment documentation.

**Interfaces:**

- Collector JSON: `sampled_at`, `interface`, `connected`, `signal_dbm`, `rx_mbps`, `tx_mbps`, `power_save` and `error`. Unknown fields are `null`; do not include PSKs, device identity or therapy filenames.
- `read_wifi_status(path: Path, now: datetime) -> dict` validates the bounded JSON and marks samples older than 60 seconds stale.
- `check_card(cfg: dict) -> dict` returns reachability, elapsed milliseconds and failure category using the configured card URL, a five-second total deadline, no redirects and bounded response reads.
- `POST /diagnostics/check`: authenticated and CSRF-protected; acquire the same nonblocking sync lock and return 409 if a sync/import is running. Rate-limit explicit checks to one per 30 seconds and show the last result.
- Add transfer totals and last-byte/completed-file timestamps, scoped by run ID. Derived recent throughput uses a rolling 60-second monotonic window and resets between runs.

- [ ] Add failing parser tests for connected/disconnected Wi-Fi, missing `iw`, permission denial, malformed/oversized JSON, an absent collector and stale samples. An unavailable diagnostic must not fail sync or health.
- [ ] Add tests for unreachable/slow card checks, redirect rejection, no extra probe during a sync, rate limiting, run-reset throughput and a healthy zero-file sync. A transfer with no new bytes for 60 seconds is “No recent transfer activity”, not a definitive Wi-Fi failure.
- [ ] Run `python -m pytest tests/test_diagnostics.py tests/test_progress.py tests/test_webapp.py -q`; confirm the new cases fail.
- [ ] Implement transfer diagnostics from existing requests. Do not poll the SD card on dashboard refresh. Show actual recent transfer speed separately from negotiated Wi-Fi link speed and suppress numeric estimates when samples are stale.
- [ ] Implement the optional collector inside the Linux guest. Run fixed argument arrays for `iw` against the administrator-configured interface, with two-second subprocess timeouts and no shell interpolation. Write JSON atomically every 15 seconds. Mount only its output directory read-only in Docker. Document “Wi-Fi details unavailable” for installations without it; do not grant the app host networking, extra capabilities or access to the Docker socket.
- [ ] Add a compact diagnostics section: card reachable/unreachable/unknown, sample age, signal strength, recent throughput and idle-only “Check connection”. Label Wi-Fi link rates as link rates so they are not mistaken for achievable SD-card transfer speed.
- [ ] Run focused tests, compare one live sample with a read-only guest measurement, and verify that disabling the collector leaves normal sync operational. Do not alter Wi-Fi power or interface configuration as part of this task.
- [ ] Commit diagnostics and installation documentation.

## Validation and rollout

- [ ] At execution start, record the current commit, Docker image IDs, active run, snapshot count and storage capacity. Reconfirm the server's current state; historical initial-sync observations are not deployment instructions.
- [ ] Run each stage's focused tests before its commit. After integration, run `python -m pytest -q` and `node --test tests/*.mjs`. Use the project test environment; the previously available environment was `/tmp/ezshare-docker-dev`, whose continued existence must be checked.
- [ ] Use synthetic card data to test stop/resume, restart recovery, concurrent export/cleanup, low disk and schedule conflicts. Do not force these failures against the owner's therapy archive.
- [ ] Test a built Docker image with the existing restricted permissions and old configuration. Verify that missing new configuration keys and absent diagnostics do not prevent startup.
- [ ] Perform rendered browser checks at desktop and narrow widths, including polling, unsaved settings, keyboard operation and clear disabled-control explanations. If browser tooling is unavailable, record this limitation and arrange manual acceptance rather than counting HTTP checks as visual testing.
- [ ] Before enabling retention, show the actual snapshots that would expire and the reclaimable space. Enable it only through the explicit settings action; deploying the code alone must not delete snapshots.
- [ ] Deploy after an active sync finishes or reaches a confirmed stop boundary. Preserve the previous image and back up configuration/state. Keep existing data mounts and credentials. Restart only the affected app service; install the optional collector separately in CT 114.
- [ ] Verify authenticated status/settings/control routes, the SMB connection ZIP, first-sync wording, next-run time and diagnostics. Import a completed snapshot into OSCAR through the read-only share as a user acceptance check.
- [ ] Exercise a guest/app restart recovery test with synthetic data first. A Proxmox host reboot is outside this rollout and requires its own maintenance window.
- [ ] Update deployment records with verified results, then push reviewed commits to the standalone repository. Capture the deployed image identifier and source commit.

### Rollback

Restore the previous image and configuration, preserving the archive and completed snapshots. New status fields must be additive so the earlier app can read state. Disable the optional collector without changing Wi-Fi configuration. Retention deletions cannot be undone by an image rollback; this is why deletion starts disabled and requires an explicit preview before activation.

## Completion criteria

The owner can see why files are or are not ready for OSCAR, stop and resume a long sync, recover after an app restart, understand the next scheduled run, connect through a configured SMB address and diagnose a missing card. Storage controls prevent avoidable overcommit and offer a clear retention policy. Existing imported files, completed snapshots and credentials survive upgrades and interrupted work.

## Execution recommendation

Implement sequentially in one isolated worktree, with a review before deploying each stage. Storage and run-control changes should receive particular attention because they affect deletion, process coordination and recovery. The requested deliverable for this turn is this plan; implementation and server changes have not started.

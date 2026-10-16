# Docker and Proxmox deployment proposal

Date: 16 October 2026

Status: Proposed design and delivery sequence. No application changes or server deployment have been made.

## Intended outcome

Run ezShareCPAP on the Proxmox server without a desktop session. Download the SD card on a schedule, retain its directory structure on persistent storage, and make a completed copy available over SMB for manual import into OSCAR on a local computer.

OSCAR continues to run locally. Its profile and database stay on the local computer; only the downloaded card directory is shared.

## Recommended deployment

Use a dedicated Debian LXC container in Proxmox, with the available Wi-Fi card assigned to it, and run Docker Compose inside it. This follows the user-confirmed hardware arrangement. Start with an unprivileged LXC and verify Wi-Fi control and nested Docker support before adopting the deployment. Run two separate services: the downloader with a built-in scheduler, and Samba serving a read-only card directory. Start with 1 vCPU and 1 GB RAM as a provisional allocation, then measure actual use. Storage must accommodate the card archive, a staging copy, retained snapshots, and backups.

Nested Docker requires the relevant LXC features, including nesting and, for unprivileged containers, keyctl as documented by Proxmox. Verify the actual guest configuration and storage driver. Do not assume a device resource entry alone grants control of a wireless network interface. Confirm the interface/PHY assignment mechanism, permissions, and restart behavior before writing deployment instructions. Do not default to a privileged LXC or disable AppArmor to make it work. If the required isolation cannot be retained, use a dedicated VM as the fallback.

Reference: https://github.com/proxmox/pve-docs/blob/master/generated/pct.conf.5-opts.adoc

Installing Docker directly on the Proxmox host is outside the proposed design.

## Card connectivity is the first prerequisite

### Observed Proxmox setup

Read-only inspection of the signed-in Proxmox page in Helium on 16 October 2026 showed:

- One node, `pve`, displaying Proxmox VE 9.2.21.
- An active LAN bridge, `vmbr0`, attached to Ethernet `enp2s0`, with address `192.168.8.231/24` and gateway `192.168.8.1`.
- An inactive network device named `wlp1s0`, with alternative name `wlxfc702e0e1f01`. Its name suggests wireless hardware, but its chipset, bus, driver, and passthrough suitability have not been verified.
- A stopped Ubuntu VM, ID 113. Its installed software, purpose, and suitability for reuse have not been inspected. No dedicated Docker VM was identifiable from the guest names alone.
- Storage entries `local`, `local-zfs`, and `usb_backup`. Their displayed usage was approximately 1.8%, 14.7%, and 37.0%, respectively. Capacities, backup coverage, and restore readiness remain unverified.
- Several existing LXC services. Their presence does not establish whether Docker is installed inside them.

The user confirmed that the server has a Wi-Fi card available for assignment to a container and that no other guest uses it. Treat this card as the planned connection to the SD card. Its assignment and operation inside the chosen LXC still need an acceptance test.

Keep the existing Ethernet bridge and host default route intact. Give the LXC a LAN interface on `vmbr0` for administration, downloads of software updates, and SMB. Configure a wireless connection to the ez Share access point inside the LXC, with only the required card-subnet route and without replacing the LAN default route or DNS. The observed LAN subnet differs from the card's default `192.168.4.0/24` subnet.

Use one network manager per interface. Leave the Proxmox-managed LAN configuration under its existing management and configure only the assigned wireless interface for the card. The guest must reconnect after the card disappears, and recover its Wi-Fi assignment after an LXC stop/start and a host reboot. Do not start or repurpose VM 113 for this design.

The Docker downloader uses the LXC's routed connectivity through its normal Docker network. It receives no Wi-Fi device, host network access, NetworkManager socket, Docker socket, or privileged mode. Network setup belongs to the outer LXC. Test the directory endpoint from inside the actual downloader, not only from the LXC shell.

A resource/device mapping is not proof of working Wi-Fi. The first deployment check is that the LXC can scan, associate with the card, receive an address, and reach its directory endpoint while retaining LAN access. Confirm chipset/driver and the interface or wireless PHY assignment method. Keep a VM with hardware passthrough or a separate client router as fallbacks if this check fails. Signal range and card power availability remain practical prerequisites.

No Proxmox configuration was changed during planning or inspection.

## What the repository already provides

- `main.py` dispatches CLI sync before importing the desktop GUI.
- `cli.py` accepts paths, URLs, retries, and configuration files, and reports process exit status.
- `ezshare.py` handles listing, counting, and downloading, but currently requires an SSID and manages connection and disconnection itself.
- `file_ops.py` preserves nested directories and usually downloads into a temporary file before replacement.
- Existing tests cover CLI behavior, connectivity, listings, and file handling.

The Docker version should reuse this code rather than implement another card downloader.

## Application changes

### 1. Add an existing-network mode

Add `--network-mode managed|existing`, retaining `managed` as the desktop default. In `existing` mode, require a valid URL and destination but no SSID or password. Create the HTTP session, verify the actual directory endpoint, and run the existing sync flow without calling Wi-Fi connect, verify, or disconnect methods, including during cancellation.

Validate configuration explicitly. The server must fail clearly on an unreadable or malformed configuration instead of silently replacing it with defaults. Keep desktop configuration behavior compatible unless a separate change is justified.

### 2. Make completed downloads reliable

Before publishing a run, distinguish a genuine empty card from malformed HTML or an unexpected web page. A missing listing marker currently becomes an empty listing. Fix the download branch that treats missing or zero Content-Length as an empty file: stream the response regardless, and check the received length when a valid length is supplied. Preserve valid empty files.

Constrain remote filenames and directories to the destination, reject traversal paths, and avoid following directory cycles. Track listing and transfer failures explicitly rather than relying solely on matching file counts. Close HTTP sessions and clean up temporary files on failure or termination.

Retain local files when they disappear from the card. This is an archive for import, so remote deletion must not delete local history. Document how to start a separate archive when changing cards or machines.

### 3. Add scheduled operation

Keep a one-run command for diagnostics and external scheduling. Add a foreground service mode with a configurable daily time and IANA timezone. Initial example: 10:00 in `Australia/Melbourne`, adjustable to when the machine has finished writing and the card remains powered.

Use a small daily calendar scheduler built on Python zoneinfo, with persistent date deduplication and explicit DST behavior. This replaces the originally proposed scheduler dependency because only one daily job is needed. Define these behaviors:

- Scheduled and manual runs share a filesystem lock. Only one may write or publish at a time.
- Run once on startup by default; make it configurable. Do not replay every missed run after downtime.
- Run at most once per scheduled local date across daylight-saving clock changes. For a skipped local time, run at the first valid time after it.
- Retry an unavailable card within a bounded window, then record failure and wait for the next scheduled run.
- Set an overall run timeout as well as request timeouts. Handle container termination without publishing an incomplete result.
- Persist the scheduled date, last attempt, last successful publication, counts, duration, and error summary outside the container image.
- Expose manual sync through a documented Compose command using the same lock and mounted storage.

Use container logs with rotation. Report scheduler liveness separately from data freshness: a running scheduler can still have an unreachable card and stale downloads.

### 4. Publish a completed copy for OSCAR

Download into a private working archive. After a fully successful run, build an immutable snapshot and atomically replace a `current` pointer on the same filesystem. Keep metadata and working files outside the shared directory.

Samba exposes the snapshot store read-only, including a `current` pointer and dated successful snapshots. Configure symlink handling to remain within that store. Retain at least the previous successful snapshot and do not remove a snapshot during an import. Start with explicit manual cleanup of old snapshots; automatic retention can follow after storage use and client behavior are tested.

Individual atomic file replacements do not make an entire card import consistent. The user should import a dated snapshot for a fixed set of files. Validate how a mounted SMB client resolves `current` during publication; do not claim that changing a pointer pins an import already in progress.

A successful snapshot means the download completed, not that the card provided a transactional view. Schedule after therapy and validate with real imports. If files change during a run, detect changes where the card supplies usable metadata and retry rather than publishing known inconsistent files.

## Container packaging and storage

Proposed additions:

- `Dockerfile`, `.dockerignore`, and a pinned server requirements file without GUI dependencies.
- `compose.yaml` for the downloader and optional Samba service.
- A focused scheduler module and persistent run-status module.
- An example server configuration, Samba configuration, and deployment guide.
- Tests for existing-network sync, scheduling, locking, publication, and download failures.

Use a supported Python slim image, a non-root downloader user, explicit UID/GID ownership, and writable mounts only where required. Persist these LXC directories:

| Directory | Purpose | Network access |
| --- | --- | --- |
| `/srv/ezshare/config` | App settings and scheduler configuration | None |
| `/srv/ezshare/state` | Lock, run status, and scheduling state | None |
| `/srv/ezshare/work` | Working card archive and staging | None |
| `/srv/ezshare/published` | Completed snapshots and current pointer | Read-only SMB |

Mount the published directory read/write in the downloader and read-only in Samba. Docker supports this arrangement through bind mounts: https://docs.docker.com/engine/storage/bind-mounts/

Choose and pin the Samba image during implementation after checking its maintenance, configuration, and UID/GID support. Require an authenticated account, disable guest writes, and restrict SMB to the home LAN. Keep credentials outside Git and logs. Samba documents `read only` and `valid users` at https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html

If an existing NAS already shares suitable storage, it can replace the Samba service after checking permissions and atomic publication on that filesystem.

## Local import workflow

Mount `smb://<vm-address>/CPAP` on the local computer. Open OSCAR, choose its CPAP card import flow, and select a completed snapshot's card root. Preserve the full card layout, not just an individual data subfolder.

Test direct import on the actual local OSCAR installation. If directory selection or SMB behavior is unreliable, copy a completed snapshot locally and import that copy. The container never launches OSCAR or accesses its local profile.

## Delivery sequence and acceptance checks

1. **Prove connectivity.** Confirm the assigned Wi-Fi card and LXC network setup, LAN/card routing, card availability, and directory access from a test container. This is the prerequisite for server deployment.
2. **Make one-run Docker sync work.** Add existing-network mode and headless dependencies. Run the existing suite plus tests proving no Wi-Fi operations occur, including on failure and cancellation. Download a real card into a persistent mount and confirm a second unchanged run skips existing data.
3. **Harden and publish downloads.** Test malformed listings, nested listing failures, unknown response lengths, truncated responses, traversal paths, changing files, disk-full conditions, and termination. Failed runs must leave the last published snapshot intact. Compare downloaded structure and representative file contents with the card.
4. **Add scheduling and status.** Test timezone changes, daylight-saving transitions, restart behavior, bounded retries, total timeout, and competing manual/scheduled runs. Confirm an unavailable card cannot produce a false success or stop later schedules.
5. **Add SMB and validate OSCAR.** Confirm authentication, read-only access, snapshot selection, and publication behavior from the actual client. Import a completed snapshot into OSCAR and confirm expected sessions appear. Repeat after another download.
6. **Document operation and recovery.** Cover LXC creation, Wi-Fi assignment, nested Docker prerequisites, Wi-Fi setup, configuration, manual sync, freshness checks, backup/restore, upgrades, and rollback. Recreate the containers and restart the LXC and reboot the Proxmox host during an agreed maintenance window to prove settings and downloaded data survive. Confirm the configured backup includes mounted data.

## First-release boundary and outstanding inputs

The first release includes Docker Compose deployment, existing-network downloads, scheduled and manual runs, persistent status, completed snapshots, and authenticated SMB. The user approved a password-protected LAN web interface with status, manual sync, schedule settings, and recent run results. Wi-Fi setup, remote access, and notifications remain outside the first release.

Before deployment, confirm where LXC storage should live, the preferred daily time, and which local OS/OSCAR installation will be used for acceptance testing. These inputs refine deployment without changing the core design.

# whyfull

**Find out why your Linux disk is full, and get the command that fixes it.**

[![CI](https://github.com/amlaban65/whyfull/actions/workflows/ci.yml/badge.svg)](https://github.com/amlaban65/whyfull/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/whyfull)](https://pypi.org/project/whyfull/)
[![Python 3.6+](https://img.shields.io/badge/python-3.6%2B-blue)](https://pypi.org/project/whyfull/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/amlaban65/whyfull/blob/main/LICENSE)

`df` says 100%. `du` doesn't add up. Something is failing with `No space left on device`.

whyfull checks the places where disk space usually goes on a Linux server: deleted files that a process still holds open, the systemd journal, Docker images and container logs, old kernels, package caches, core dumps, runaway logs and inode exhaustion. For each thing it finds, it prints how much space it takes, how risky it is to remove, and the exact command to get the space back.

It never deletes anything itself.

Prefer to fix it by hand? The [guides](https://amlaban65.github.io/whyfull/) walk through each cause: [freeing space on an Ubuntu server](https://amlaban65.github.io/whyfull/guides/free-up-disk-space-ubuntu-server/), [df vs du](https://amlaban65.github.io/whyfull/guides/df-full-du-does-not-add-up/), [deleted files still using space](https://amlaban65.github.io/whyfull/guides/deleted-files-still-using-space/), [Docker](https://amlaban65.github.io/whyfull/guides/docker-disk-space/), [Kubernetes nodes](https://amlaban65.github.io/whyfull/guides/kubernetes-node-disk-full/), [the systemd journal](https://amlaban65.github.io/whyfull/guides/journalctl-disk-usage/), [inodes](https://amlaban65.github.io/whyfull/guides/no-space-left-on-device-but-df-shows-free-space/), [/var/log](https://amlaban65.github.io/whyfull/guides/var-log-full/) and [old kernels](https://amlaban65.github.io/whyfull/guides/boot-full-remove-old-kernels/).

<p align="center">
  <img src="https://raw.githubusercontent.com/amlaban65/whyfull/main/docs/demo.svg" alt="whyfull showing a full root filesystem: a 700 MB deleted nginx log still held open, a 560 MB Docker container log, unused images, old kernels and the systemd journal, each with the command that frees it" width="100%">
</p>

## Run it

A full disk may leave no room to install anything, so whyfull is a single 35 KB file with no dependencies. It runs on the Python 3 that already ships with nearly every Linux server (3.6 or newer). Download it to `/dev/shm`, which lives in memory:

```sh
curl -fsSL -o /dev/shm/whyfull https://github.com/amlaban65/whyfull/releases/latest/download/whyfull.pyz
sudo python3 /dev/shm/whyfull
```

Or install it from PyPI:

```sh
pipx install whyfull      # or: uv tool install whyfull, pip install --user whyfull
sudo "$(command -v whyfull)"
```

`uvx whyfull` and `pipx run whyfull` work for a one-off run.

Run it with `sudo`. Without root it can't measure files owned by other users and services, and it will tell you what it couldn't read.

## What it looks for

| Check | What it finds |
|---|---|
| `deleted-open` | Files that were deleted while a process still had them open. This is the classic "df says full but du says otherwise". whyfull names the systemd service or Docker container holding them and shows how to release the space with or without a restart. |
| `docker` | Build cache, unused images, stopped containers, dangling volumes, and container logs with no size limit. |
| `cri` | Unused containerd/CRI-O images reported by `crictl`; running and stopped container references are preserved. Shared layers can reduce the actual reclaimed space. |
| `podman` | Reclaimable rootful Podman images and stopped containers outside CRI-O nodes. Rootless stores are measured from disk and labeled informational; no other user's Podman commands are run. |
| `journald` | A systemd journal that has grown past a sensible size, with the commands to vacuum it and cap it. |
| `logs` | Rotated and compressed logs in `/var/log`, and single log files over 1 GB. |
| `pod-logs` | The largest kubelet pod log directories, with rotation settings and explicitly cautious truncation commands. |
| `kernels` | Installed kernels other than the running one and the newest one, with the right removal command for apt, dnf or zypper. |
| `packages` | apt, dnf, yum, pacman, zypper and apk caches. |
| `snaps` | Disabled snap revisions that snapd keeps around. |
| `crashes` | Core dumps from systemd-coredump, apport and ABRT, and `/var/crash`. |
| `tmp` | Files in `/tmp` and `/var/tmp` nobody has touched in a week. |
| `user-caches` | pip, uv, poetry, npm, yarn, pnpm, Go, Cargo, Maven, Gradle, Hugging Face, PyTorch and conda caches, and the Trash, for every user. |
| `android` | Per-user emulator data and SDK system images, with Android tooling commands for reviewing and removing selected items. |
| `mysql` | MySQL and MariaDB binary logs in `/var/lib/mysql`, with the `PURGE BINARY LOGS` and `binlog_expire_logs_seconds` fixes. |
| `inodes` | A filesystem that ran out of inodes (too many files) rather than bytes, and the directories with the most entries. |
| `reserved` | ext filesystems that look full only because of the 5% reserved for root. |

whyfull also scans the whole filesystem (with a time limit) and lists the largest directories. When the files it can see add up to much less than `df` reports, it says so, and points to where the rest usually is. Common causes are files hidden underneath a mount point and btrfs or ZFS snapshots.

`whyfull --list-checks` prints the list from your installed version.

### Risk levels

Every finding is labelled so you know what you're agreeing to:

- **safe**: caches that are rebuilt on demand. Removing them costs a slower next build or download.
- **review**: almost always fine to remove (old kernels, rotated logs, unused images), but take a look first.
- **caution**: can lose data or affect a running service, such as truncating a live log or pruning Docker volumes.
- **info**: explains what's going on, like inode exhaustion or the root reserve, without a direct cleanup.

## Usage

```sh
sudo whyfull                      # every filesystem that is 85% full or more
sudo whyfull /var                 # only the filesystem holding /var
sudo whyfull -t 70                # lower the "full" threshold to 70%
sudo whyfull -v                   # explain every finding, list all evidence
sudo whyfull --no-scan            # skip the full scan, run only the checks
sudo whyfull --exclude /var/lib/db --exclude /media  # skip known paths in the full scan
sudo whyfull --only docker,logs   # run some checks; see --list-checks
```

`--exclude PATH` is repeatable and only affects the full scan. Excluded files
and directories are omitted from scan totals and largest-directory listings;
targeted checks still inspect them. When exclusions are set, whyfull skips the
unexplained-space finding and adds a report note, since comparing a partial
scan with `df` would otherwise make excluded data look like missing space.

If nothing is above the threshold, whyfull analyses `/` anyway and tells you the disks are fine.

### For incident tickets, scripts and monitoring

```sh
sudo whyfull --format markdown > disk.md   # paste into a ticket or chat
sudo whyfull --json | jq '.targets[].findings[] | {title, bytes, risk}'
whyfull --fail-above 90 --no-scan          # exits 1 when any filesystem is 90%+ full
```

Exit codes: `0` when the run finished, `1` when `--fail-above` was exceeded, `2` for usage errors.

## How is this different from ncdu, du, dust or gdu?

Those are great for browsing a directory tree, and you should keep using them. They answer "which folder is big". whyfull answers "what is this space, and how do I get it back without breaking anything". It finds space that no directory browser can see (deleted files held open by a process). It knows that `/var/lib/docker/overlay2` is cleaned with `docker image prune`, not `rm`. It knows which kernels are safe to remove, and that a 2 GB `syslog.2.gz` can go while a live `syslog` should be truncated.

Run whyfull first. If something is still unexplained, open ncdu on the directory it points to.

## Safety

- whyfull only reads. It does not delete, truncate, prune or restart anything.
- The only commands it runs are read-only: `docker system df`, `docker info`, `crictl images`, `crictl ps -a`, `podman system df` and `snap list --all`.
- Every fix is printed for you to read and run yourself. Commands that can lose data are marked **caution** and explained.
- Scans stay on one filesystem (like `du -x`), count hard links once, and stop at a time limit, so they won't hang on a huge disk or wander into network mounts.

## Contributing

The most useful contribution is a new check: *"my disk filled up because of X, and here is how to spot it and clean it up."* Each check is one short file in [`src/whyfull/checks/`](https://github.com/amlaban65/whyfull/tree/main/src/whyfull/checks), and tests run against a fake filesystem, so you don't need a full disk to write one. [CONTRIBUTING.md](https://github.com/amlaban65/whyfull/blob/main/CONTRIBUTING.md) walks through it.

Some checks that would help a lot of people: PostgreSQL WAL, Elasticsearch, Prometheus, LXD, Flatpak, Jenkins workspaces, libvirt disk images, CI runner work directories, and btrfs or ZFS snapshots. The [open issues](https://github.com/amlaban65/whyfull/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) describe several of them in detail. If you have a war story about a disk that filled up in a strange way, [open an issue](https://github.com/amlaban65/whyfull/issues/new?template=new-check.yml) even if you don't plan to write the code.

## License

[MIT](https://github.com/amlaban65/whyfull/blob/main/LICENSE)

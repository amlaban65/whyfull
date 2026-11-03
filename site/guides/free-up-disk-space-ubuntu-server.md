---
title: Free up disk space on an Ubuntu or Debian server
description: A safe order for getting space back on a full Ubuntu or Debian server, from finding what's using it to cleaning apt, old kernels, the journal, logs, snaps, Docker and core dumps.
short: The usual places, in a safe order.
---

When a server runs out of space, it's tempting to start deleting whatever looks big. Most of the space on an Ubuntu or Debian server is in a handful of predictable places, and each has a command that cleans it safely. Work through them in this order: the first steps are the safest and often free enough on their own.

## 1. See what's full

```sh
df -h
df -i
```

`df -h` shows space per filesystem. `df -i` shows inodes: if `IUse%` is at 100%, the problem is too many small files, not too many bytes, and the [inodes guide](../no-space-left-on-device-but-df-shows-free-space/) covers that instead.

## 2. Find where the space is

```sh
sudo du -xh --max-depth=1 / | sort -h
```

`-x` keeps `du` on one filesystem, so it doesn't count other disks mounted under `/`. Run it again on the biggest directory (`/var` is the usual one) until you know what's using the space. If the total is much smaller than what `df` reports, read [df says full but du doesn't add up](../df-full-du-does-not-add-up/) before deleting anything.

## 3. Clear the apt cache

apt keeps every package it has downloaded in `/var/cache/apt/archives`. They're only needed to reinstall without downloading again.

```sh
sudo du -sh /var/cache/apt
sudo apt clean
```

Then remove packages that were installed as dependencies and are no longer needed:

```sh
sudo apt autoremove --purge
```

Read the list before you confirm. It usually includes old kernels, which is what you want, but check that nothing you still use is on it.

## 4. Remove old kernels

Each kernel takes a few hundred MB across `/boot` and `/lib/modules`. `apt autoremove` removes most of them. If old kernels are still installed, or `/boot` is a separate partition that's full, follow [removing old kernels](../boot-full-remove-old-kernels/).

## 5. Shrink the systemd journal

```sh
journalctl --disk-usage
sudo journalctl --vacuum-size=500M
```

To stop it growing back, set `SystemMaxUse=500M` in `/etc/systemd/journald.conf` and run `sudo systemctl restart systemd-journald`. The [journal guide](../journalctl-disk-usage/) has the details.

## 6. Deal with large logs in /var/log

Old rotated logs (`syslog.2.gz`, `auth.log.1`) can be removed. A log that is still being written to should be truncated, not deleted, because deleting it doesn't free the space while the program has it open:

```sh
sudo truncate -s 0 /var/log/syslog
```

If one log keeps filling the disk, find out why the program is logging so much, and have logrotate rotate it by size. See [/var/log is full](../var-log-full/).

## 7. Remove old snap revisions

snapd keeps old revisions of every snap. List the disabled ones:

```sh
snap list --all | awk '/disabled/ {print $1, $3}'
```

Remove each one by name and revision:

```sh
sudo snap remove firefox --revision=4793
```

To keep only two revisions from now on (the minimum):

```sh
sudo snap set system refresh.retain=2
```

## 8. Clean up Docker

On a server that runs containers, Docker is often the biggest thing on the disk.

```sh
docker system df
docker image prune -a
docker builder prune
```

`docker image prune -a` removes images that no container uses, and `docker builder prune` removes the build cache. Be careful with `docker volume prune`: volumes hold data, and unused isn't always the same as unwanted. Container logs without a size limit are another common cause. The [Docker guide](../docker-disk-space/) covers both.

## 9. Delete old core dumps

When a program crashes, apport (Ubuntu) and systemd-coredump can keep a dump of its memory, sometimes several GB each.

```sh
sudo du -sh /var/crash /var/lib/systemd/coredump
coredumpctl list
```

If you don't need them to debug the crash, remove them:

```sh
sudo rm -f /var/crash/*.crash
sudo rm -f /var/lib/systemd/coredump/*
```

## 10. Check caches in home directories

Build tools keep large caches in each user's home directory: pip, npm, Go, Cargo, Maven, Gradle, Hugging Face models. They're rebuilt when needed.

```sh
sudo du -sh /home/*/.cache /root/.cache 2>/dev/null | sort -h
```

Use each tool's own cleanup command where it has one, for example `pip cache purge`, `npm cache clean --force` or `go clean -cache`, run as the user who owns the cache.

## If df still says full

If you've deleted files and `df` hasn't moved, a process still has them open. Find it with:

```sh
sudo lsof +L1
```

Restarting that process frees the space. [Deleted files still using space](../deleted-files-still-using-space/) explains how to free it without a restart.

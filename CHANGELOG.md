# Changelog

## 0.2.0

New checks, all contributed:

- `cri`: unused containerd and CRI-O images on Kubernetes nodes, from `crictl` (#11, @Sarbajit-Sengupta).
- `pod-logs`: the largest kubelet pod log directories in `/var/log/pods`, without double-counting them in `logs` (#12, @Sarbajit-Sengupta).
- `mysql`: MySQL and MariaDB binary logs (#7, @arin30).
- `podman`: reclaimable rootful Podman images and stopped containers, and the size of rootless storage (#13, @Sarbajit-Sengupta).
- `android`: Android emulator data and SDK system images in home directories (#20, @Sarbajit-Sengupta).

Other changes:

- `--exclude PATH` skips known paths during the full scan. It can be repeated (#19, @YinL-k).
- Suggested `truncate` commands quote log paths, so paths with spaces work (#9, @arin30).
- `logs`: the cleanup command for rotated logs now also removes the `.zip` archives the check counts (#25, @barkya28).
- `user-caches`: the PyTorch finding measures only `~/.cache/torch/hub`, the part its fix removes (#24, @barkya28).
- New website guide: freeing disk space on a Kubernetes node (#23, @Sarbajit-Sengupta).

## 0.1.0

First release.

- Checks: deleted-but-open files, Docker (build cache, images, containers, volumes, container logs), systemd journal, rotated and oversized logs, old kernels, package manager caches, snap revisions, core dumps, old temp files, user build and package caches, inode exhaustion, and the ext root reserve.
- Full-filesystem scan with a time limit, largest directories, crowded directories, and a warning when `df` and the files on disk don't add up.
- Text, JSON and Markdown output; `--fail-above` for cron and monitoring.
- Runs on Python 3.6+ with no dependencies; also shipped as a single `whyfull.pyz` file.

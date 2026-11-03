---
title: Podman using too much disk space
description: Free disk space used by Podman images, containers and volumes, for both rootful storage in /var/lib/containers and rootless storage in each user's home directory.
short: Clean rootful and rootless Podman storage.
---

Podman keeps images, containers and volumes in two different places, depending on who runs it:

- **Rootful** (run with `sudo`): `/var/lib/containers/storage`
- **Rootless** (run as a normal user): `~/.local/share/containers/storage` in each user's home directory

That second one is easy to miss. On a shared machine or a CI runner, every user who has run Podman has their own copy of the images they pulled, and running `sudo podman` doesn't show any of it.

As with Docker, **don't delete files under the storage directory by hand.** Use Podman's own commands, which keep the image and container records consistent.

## See what's using the space

For rootful storage:

```sh
sudo podman system df
```

For your own rootless storage, run it without `sudo`:

```sh
podman system df
```

The `RECLAIMABLE` column shows what the cleanup commands below can free. Add `-v` to see each image, container and volume.

To find other users' rootless storage, measure it from the outside:

```sh
sudo du -sh /home/*/.local/share/containers/storage 2>/dev/null | sort -h
```

Each user has to clean their own rootless storage, logged in as themselves, because their files belong to their own user namespace.

## Clean up

Remove stopped containers:

```sh
podman container prune
```

Remove images that no container uses (without `-a`, only untagged "dangling" images are removed):

```sh
podman image prune -a
```

Or do both, plus unused pods and networks, in one go:

```sh
podman system prune -a
```

Add `sudo` to each command for rootful storage.

**Volumes hold data.** `podman volume prune` and `podman system prune --volumes` delete every volume no container is using, including ones a stopped service will need again. List them first with `podman volume ls` and remove only the ones you know are unwanted, with `podman volume rm NAME`.

## The last resort

`podman system reset` deletes all images, containers, volumes and configuration in that storage, as if Podman had just been installed. It's useful when the storage itself is broken. It is not a cleanup command: everything is gone afterwards.

## Keep it from growing back

- On build machines, run `podman system prune -a -f` from a timer or cron job for the users that build images.
- Use `podman run --rm` for one-off containers so they're removed when they exit.
- With the `k8s-file` log driver, container logs live in the container's directory under storage. Cap them with `--log-opt max-size=50m`, or set `log_size_max` in `containers.conf`. Many distributions default to the `journald` driver instead, and then the logs go to the [systemd journal](../journalctl-disk-usage/).

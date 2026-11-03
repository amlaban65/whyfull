"""Podman reclaimable resources and per-user rootless storage."""

import json
import os
import shlex

from whyfull.checks import check
from whyfull.model import INFO, REVIEW, Finding
from whyfull.units import parse_size

MIN_BYTES = 200 * 10 ** 6
ROOT = "/var/lib/containers/storage"
ROWS = {
    "Images": ("images", "images not used by containers", "image prune -a -f"),
    "Containers": ("containers", "stopped containers", "container prune -f"),
}


def _reclaimable(ctx, path, prefix, owner):
    out = ctx.system.run(prefix + ["podman", "system", "df", "--format", "json"], timeout=60)
    try:
        rows = json.loads(out or "null")
        if not isinstance(rows, list):
            raise ValueError("expected rows")
    except (ValueError, TypeError):
        ctx.note("Podman inventory for %s was unavailable; total storage is not assumed reclaimable." % owner)
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        spec = ROWS.get(row.get("Type"))
        if spec is None:
            continue
        raw = row.get("RawReclaimable")
        if isinstance(raw, int) and not isinstance(raw, bool):
            size = raw
        else:
            size = parse_size(str(row.get("Reclaimable", "")).split(" (")[0])
        if not size or size < MIN_BYTES:
            continue
        key, title, command = spec
        lead = " ".join(shlex.quote(arg) for arg in prefix)
        fix = (lead + " " if lead else "") + "podman " + command
        yield Finding(
            "podman", owner + ":" + key, "Podman %s (%s)" % (title, owner),
            size, REVIEW, ctx.dev_of(path),
            detail=("Podman's reclaimable estimate may include shared image layers, so pruning can free less. "
                    "Review stopped containers before pruning their writable layers."),
            fix=[fix],
        )


@check("podman", "Podman images, stopped containers and rootless storage")
def run(ctx):
    if not ctx.system.has("podman"):
        return
    # CRI-O shares this store, but Podman cannot see kubelet container references.
    crio = ctx.system.has("crictl") or ctx.system.exists("/etc/crio")
    if not crio and ctx.system.exists(ROOT) and ctx.on_target(ROOT):
        yield from _reclaimable(ctx, ROOT, [], "rootful")
    for name, home in ctx.system.users():
        path = os.path.join(home, ".local/share/containers/storage")
        if not ctx.system.exists(path) or not ctx.on_target(path):
            continue
        # Even an inventory command can initialize another user's Podman store.
        # Measure files only; leave owner-specific commands for the user to run.
        size = ctx.size(path)
        if size >= MIN_BYTES:
            yield Finding(
                "podman", name + ":storage", "Podman rootless storage for %s" % name,
                size, INFO, ctx.dev_of(path),
                detail=("Total allocated storage, including resources still in use. "
                        "This is not an estimate of reclaimable space."),
                fix=["# inspect this user's storage before choosing a prune command:",
                     "sudo -u %s -H podman system df" % shlex.quote(name)],
            )

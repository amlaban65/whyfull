"""Space held by ZFS and Btrfs snapshots."""

import shlex

from whyfull.checks import check
from whyfull.model import CAUTION, INFO, Finding
from whyfull.units import human

MIN_BYTES = 200 * 10 ** 6
MAX_EVIDENCE = 5


def _zfs_usage(output, dataset):
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("expected one ZFS dataset usage row")
    fields = lines[0].split("\t")
    if len(fields) != 2 or fields[0] != dataset:
        raise ValueError("invalid ZFS dataset usage row")
    size = int(fields[1])
    if size < 0:
        raise ValueError("negative ZFS snapshot usage")
    return size


def _zfs_snapshots(output):
    snapshots = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 2 or "@" not in fields[0]:
            raise ValueError("invalid ZFS snapshot row")
        size = int(fields[1])
        if size < 0:
            raise ValueError("negative ZFS snapshot size")
        snapshots.append((fields[0], size))
    return snapshots


def _btrfs_snapshots(output):
    snapshots = []
    for line in output.splitlines():
        if not line.strip():
            continue
        if not line.startswith("ID ") or " path " not in line:
            raise ValueError("invalid Btrfs snapshot row")
        snapshots.append(line.split(" path ", 1)[1])
    return snapshots


def _snapshot_manager_fixes():
    return [
        "# If Snapper manages these snapshots, inspect them and delete only selected IDs.",
        "sudo snapper list",
        "sudo snapper delete N",
        "# If Timeshift manages them, inspect the list and delete only a selected snapshot.",
        "sudo timeshift --list",
        "sudo timeshift --delete --snapshot 'SNAPSHOT'",
    ]


@check("snapshots", "Space held by Btrfs and ZFS snapshots")
def run(ctx):
    for fs in ctx.targets:
        fstype = (fs.fstype or "").lower()
        if not ctx.on_target(fs.mountpoint):
            continue

        if fstype == "zfs":
            dataset = fs.source
            if not dataset or dataset == "-":
                ctx.note("ZFS snapshot usage could not be measured because the dataset name is unavailable.")
                continue
            if not ctx.system.has("zfs"):
                ctx.note("ZFS snapshot usage could not be measured because the zfs command is unavailable.")
                continue
            output = ctx.system.run([
                "zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", dataset,
            ])
            if output is None:
                ctx.note("ZFS snapshot usage could not be read for %s." % dataset)
                continue
            try:
                size = _zfs_usage(output, dataset)
            except (TypeError, ValueError):
                ctx.note("ZFS returned incomplete or invalid snapshot usage for %s." % dataset)
                continue
            if size < MIN_BYTES:
                continue

            evidence = [
                "Dataset: %s" % dataset,
                "Space held by snapshots: %s (%d bytes)" % (human(size), size),
            ]
            # ZFS uses -S for descending order; -s would put the smallest snapshots first.
            snapshot_output = ctx.system.run([
                "zfs", "list", "-H", "-p", "-t", "snapshot",
                "-o", "name,used", "-S", "used", "-r", dataset,
            ])
            if snapshot_output is None:
                ctx.note("The largest ZFS snapshots could not be listed for %s." % dataset)
            else:
                try:
                    snapshots = _zfs_snapshots(snapshot_output)
                    evidence.extend(
                        "%s: %s (%d bytes)" % (name, human(used), used)
                        for name, used in snapshots[:MAX_EVIDENCE]
                    )
                except (TypeError, ValueError):
                    ctx.note("ZFS returned an invalid snapshot inventory for %s." % dataset)

            fixes = _snapshot_manager_fixes()
            fixes.extend([
                "# Fallback: destroy only an individually reviewed ZFS snapshot.",
                "sudo zfs destroy %s" % shlex.quote(dataset + "@SNAP"),
            ])
            yield Finding(
                "snapshots", dataset,
                "ZFS snapshots on %s hold %s" % (dataset, human(size)),
                size, CAUTION, fs.dev,
                detail=(
                    "ZFS usedbysnapshots reports the space that would be freed by destroying "
                    "all snapshots of this dataset. The per-snapshot used values below are "
                    "evidence, not additive reclaimable amounts. Deleting a snapshot is permanent; "
                    "check replication, backups and rollback requirements first."
                ),
                fix=fixes,
                evidence=evidence,
            )

        elif fstype == "btrfs":
            if not ctx.system.is_root:
                ctx.note(
                    "Btrfs snapshots could not be listed on %s; run whyfull as root to inspect them."
                    % fs.mountpoint
                )
                continue
            if not ctx.system.has("btrfs"):
                ctx.note("Btrfs snapshots could not be listed because the btrfs command is unavailable.")
                continue
            output = ctx.system.run(["btrfs", "subvolume", "list", "-s", fs.mountpoint])
            if output is None:
                ctx.note("Btrfs snapshot inventory could not be read on %s." % fs.mountpoint)
                continue
            try:
                snapshots = _btrfs_snapshots(output)
            except (TypeError, ValueError):
                ctx.note("Btrfs returned an incomplete or invalid snapshot inventory on %s." % fs.mountpoint)
                continue
            if not snapshots:
                continue

            fixes = _snapshot_manager_fixes()
            fixes.extend([
                "# Fallback: resolve the path from the filesystem top level before deleting one subvolume.",
                "sudo btrfs subvolume delete 'PATH'",
            ])

            yield Finding(
                "snapshots", fs.mountpoint,
                "%d Btrfs snapshots on %s" % (len(snapshots), fs.mountpoint),
                0, INFO, fs.dev,
                detail=(
                    "Btrfs snapshot count is reported without estimating reclaimable bytes. "
                    "Exclusive snapshot usage requires usable qgroup accounting; this check does "
                    "not infer a size from subvolume listings. Deleting a snapshot is permanent; "
                    "confirm no backup or rollback depends on it."
                ),
                fix=fixes,
                evidence=["Snapshot count: %d" % len(snapshots)] + [
                    "Snapshot path: %s" % path for path in snapshots[:MAX_EVIDENCE]
                ],
            )

from conftest import make_ctx

from whyfull.checks import snapshots
from whyfull.model import CAUTION, INFO


def findings(ctx):
    return list(snapshots.run(ctx) or [])


def test_zfs_reports_reclaimable_snapshot_space_and_largest_snapshots(root, monkeypatch):
    monkeypatch.setattr(snapshots, "MIN_BYTES", 1000)
    dataset = "tank/data"
    root.commands[("zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", dataset)] = (
        dataset + "\t1048576000\n"
    )
    root.commands[(
        "zfs", "list", "-H", "-p", "-t", "snapshot", "-o", "name,used", "-S", "used", "-r", dataset,
    )] = (
        "tank/data@daily-1\t800000000\n"
        "tank/data@daily-2\t200000000\n"
        "tank/data@daily-3\t50000000\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "zfs"
    ctx.targets[0].source = dataset

    f, = findings(ctx)

    assert f.check == "snapshots"
    assert f.key == dataset
    assert f.bytes == 1048576000
    assert f.risk == CAUTION
    assert f.dev == ctx.targets[0].dev
    assert "tank/data@daily-1" in f.evidence
    assert any("zfs destroy" in line and "tank/data@SNAP" in line for line in f.fix)
    assert any("snapper list" in line for line in f.fix)
    assert any("timeshift --list" in line for line in f.fix)


def test_zfs_skips_small_snapshot_usage(root, monkeypatch):
    monkeypatch.setattr(snapshots, "MIN_BYTES", 1000)
    dataset = "tank/data"
    root.commands[("zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", dataset)] = (
        dataset + "\t999\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "zfs"
    ctx.targets[0].source = dataset

    assert findings(ctx) == []


def test_zfs_reports_usage_when_snapshot_inventory_is_unavailable(root, monkeypatch):
    monkeypatch.setattr(snapshots, "MIN_BYTES", 1000)
    dataset = "tank/data"
    root.commands[("zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", dataset)] = (
        dataset + "\t5000\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "zfs"
    ctx.targets[0].source = dataset

    f, = findings(ctx)

    assert f.bytes == 5000
    assert any("could not be listed" in note for note in ctx.notes)
    assert not any("tank/data@" in item for item in f.evidence)


def test_zfs_ignores_invalid_usage_output(root):
    dataset = "tank/data"
    root.commands[("zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", dataset)] = (
        "tank/other\t5000\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "zfs"
    ctx.targets[0].source = dataset

    assert findings(ctx) == []
    assert any("invalid snapshot usage" in note for note in ctx.notes)


def test_btrfs_reports_count_without_claiming_reclaimable_bytes(root):
    root.commands[("btrfs", "subvolume", "list", "-s", "/")] = (
        "ID 256 gen 100 top level 5 path @snapshots/one\n"
        "ID 257 gen 110 top level 5 path @snapshots/two\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "btrfs"

    f, = findings(ctx)

    assert f.check == "snapshots"
    assert f.bytes == 0
    assert f.risk == INFO
    assert f.evidence == [
        "Snapshot count: 2",
        "Snapshot path: @snapshots/one",
        "Snapshot path: @snapshots/two",
    ]
    assert "sudo btrfs subvolume delete 'PATH'" in f.fix
    assert "sudo snapper delete N" in f.fix
    assert "sudo timeshift --delete --snapshot 'SNAPSHOT'" in f.fix


def test_btrfs_with_no_snapshots_has_no_finding(root):
    root.commands[("btrfs", "subvolume", "list", "-s", "/")] = ""
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "btrfs"

    assert findings(ctx) == []


def test_btrfs_requires_root(root):
    root.commands[("btrfs", "subvolume", "list", "-s", "/")] = (
        "ID 256 gen 100 top level 5 path @snapshots/one\n"
    )
    ctx = make_ctx(root.system(euid=1000))
    ctx.targets[0].fstype = "btrfs"

    assert findings(ctx) == []
    assert any("run whyfull as root" in note for note in ctx.notes)


def test_btrfs_handles_unavailable_inventory(root):
    root.commands[("btrfs", "subvolume", "list", "-s", "/")] = None
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "btrfs"

    assert findings(ctx) == []
    assert any("could not be read" in note for note in ctx.notes)


def test_other_filesystem_types_are_ignored(root):
    root.commands[("zfs", "list", "-H", "-p", "-o", "name,usedbysnapshots", "tank/data")] = (
        "tank/data\t5000\n"
    )
    root.commands[("btrfs", "subvolume", "list", "-s", "/")] = (
        "ID 256 gen 100 top level 5 path @snapshots/one\n"
    )
    ctx = make_ctx(root.system())
    ctx.targets[0].fstype = "ext4"

    assert findings(ctx) == []

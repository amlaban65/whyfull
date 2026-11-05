import os
import stat

import pytest

from conftest import make_ctx
from whyfull.checks import load
from whyfull.model import INFO

PATH = "/var/lib/prometheus"
TOTAL = 6 * 10 ** 9


def findings(ctx):
    return [f for check in load() if check.id == "prometheus" for f in check.fn(ctx)]


def prepared(root, monkeypatch, path=PATH, marker="wal"):
    root.write(path + "/" + marker + "/segment", size=60000)
    ctx = make_ctx(root.system())
    monkeypatch.setattr(ctx, "size", lambda p: TOTAL if p == path else 3 * 10 ** 9)
    monkeypatch.setattr(ctx.system, "run", lambda *a, **kw: pytest.fail("command executed"))
    return ctx


@pytest.mark.parametrize("path", [PATH, PATH + "/metrics2"])
@pytest.mark.parametrize("marker", ["wal", "chunks_head"])
def test_informational_total_and_safe_guidance(root, monkeypatch, path, marker):
    ctx = prepared(root, monkeypatch, path, marker)
    found = findings(ctx)
    assert len(found) == 1
    f = found[0]
    assert f.key == path and f.bytes == TOTAL and f.risk == INFO
    assert "not reclaimable" in f.detail and "Never delete" in f.detail
    assert "persistent blocks only" in f.detail
    assert "promtool tsdb analyze " + path in f.fix
    assert any("retention.size=50GB" in line for line in f.fix)
    assert all(not line.startswith("rm ") for line in f.fix)
    if marker == "wal":
        assert "3000000000 bytes, included" in f.detail
        assert "does not prove" in f.detail
    else:
        assert "not measured separately" in f.detail


def test_missing_marker_regular_files_and_small_stores(root, monkeypatch):
    ctx = make_ctx(root.system())
    assert findings(ctx) == []
    root.write(PATH + "/unrelated", size=10000)
    assert findings(ctx) == []
    root.write(PATH + "/wal", size=10000)
    assert findings(ctx) == []


def test_floor_and_normal_wal(root, monkeypatch):
    ctx = prepared(root, monkeypatch)
    monkeypatch.setattr(ctx, "size", lambda p: TOTAL if p == PATH else 10000)
    assert "Large WAL" not in findings(ctx)[0].detail
    monkeypatch.setattr(ctx, "size", lambda p: 5 * 10 ** 9 - 1)
    assert findings(ctx) == []
    monkeypatch.setattr(ctx, "size", lambda p: 5 * 10 ** 9)
    assert findings(ctx)[0].bytes == 5 * 10 ** 9


def test_nested_store_not_counted_twice(root, monkeypatch):
    ctx = prepared(root, monkeypatch)
    root.write(PATH + "/metrics2/wal/segment", size=60000)
    assert len(findings(ctx)) == 1


def test_off_target_store_is_not_measured(root, monkeypatch):
    root.write(PATH + "/wal/segment", size=60000)
    root.mounts.append((PATH, "ext4", "/dev/sdb1"))
    ctx = make_ctx(root.system())
    monkeypatch.setattr(ctx, "size", lambda p: pytest.fail("off-target store measured"))
    assert findings(ctx) == []


@pytest.mark.parametrize("link_path", [PATH, PATH + "/wal"])
def test_symlink_root_or_only_marker_is_skipped(root, monkeypatch, link_path):
    ctx = prepared(root, monkeypatch)
    original = ctx.system.lstat

    class Link(object):
        st_mode = stat.S_IFLNK

    monkeypatch.setattr(ctx.system, "lstat", lambda p: Link() if p == link_path else original(p))
    monkeypatch.setattr(ctx, "size", lambda p: pytest.fail("symlink measured"))
    assert findings(ctx) == []


def test_other_device_wal_is_not_measured(root, monkeypatch):
    root.write(PATH + "/wal/segment", size=60000)
    root.mounts.append((PATH + "/wal", "ext4", "/dev/sdb1"))
    ctx = make_ctx(root.system())

    def size(path):
        assert path == PATH
        return TOTAL

    monkeypatch.setattr(ctx, "size", size)
    assert "not measured separately" in findings(ctx)[0].detail


@pytest.mark.skipif(os.name == "nt", reason="Allocated-block traversal requires Linux")
def test_real_allocated_measurement(root, monkeypatch):
    from whyfull.checks import prometheus

    monkeypatch.setattr(prometheus, "MIN_BYTES", 20000)
    root.write(PATH + "/wal/segment", size=60000)
    root.write(PATH + "/block/chunks/000001", size=60000)
    ctx = make_ctx(root.system())
    f, = findings(ctx)
    assert f.bytes == ctx.size(PATH) and f.bytes >= 120000
    assert "WAL: %d bytes, included" % ctx.size(PATH + "/wal") in f.detail

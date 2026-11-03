import json

import pytest

from conftest import make_ctx
from whyfull.checks import podman
from whyfull.model import INFO, REVIEW


def test_rootful_reclaimable_counts_and_safe_read_commands(root, monkeypatch):
    monkeypatch.setattr(podman, "MIN_BYTES", 20000)
    root.mkdir(podman.ROOT)
    root.commands[("podman", "system", "df", "--format", "json")] = json.dumps([
        {"Type": "Images", "RawReclaimable": 50000},
        {"Type": "Containers", "Reclaimable": "30kB (50%)"},
        {"Type": "Local Volumes", "RawReclaimable": 90000},
    ])
    findings = list(podman.run(make_ctx(root.system())))
    assert [f.bytes for f in findings] == [50000, 30000]
    assert all(f.risk == REVIEW for f in findings)
    assert findings[0].fix == ["podman image prune -a -f"]
    assert findings[1].fix == ["podman container prune -f"]


def test_rootless_storage_is_info_without_running_as_owner(root, monkeypatch):
    monkeypatch.setattr(podman, "MIN_BYTES", 20000)
    root.write("/home/alice/.local/share/containers/storage/layer", size=50000)
    root.commands[("podman", "--version")] = "podman version fixture"
    # This output must never be requested, even when whyfull is run as root.
    root.commands[("sudo", "-u", "alice", "-H", "podman", "system", "df", "--format", "json")] = json.dumps([
        {"Type": "Images", "RawReclaimable": 50000},
    ])
    system = root.system()
    commands = []
    runner = system._runner

    def record(argv):
        commands.append(list(argv))
        return runner(argv)

    system._runner = record
    finding, = list(podman.run(make_ctx(system)))
    assert finding.bytes >= 50000
    assert finding.risk == INFO
    assert finding.fix[-1] == "sudo -u alice -H podman system df"
    assert not any(cmd[0] == "sudo" for cmd in commands)
    assert not any(cmd[:3] == ["podman", "system", "df"] for cmd in commands)


def test_unavailable_rootless_inventory_is_total_usage_not_reclaimable(root, monkeypatch):
    monkeypatch.setattr(podman, "MIN_BYTES", 20000)
    root.write("/home/alice/.local/share/containers/storage/layer", size=50000)
    root.commands[("podman", "--version")] = "podman version fixture"
    finding, = list(podman.run(make_ctx(root.system())))
    assert finding.risk == INFO
    assert "not an estimate of reclaimable" in finding.detail
    assert not any("prune -" in command for command in finding.fix)


def test_bad_rootful_output_and_missing_tool_do_not_claim_space(root):
    root.mkdir(podman.ROOT)
    assert list(podman.run(make_ctx(root.system()))) == []
    for output in ("broken", "null", "{}", "[null]", '[{"Type":"Images","RawReclaimable":-1}]'):
        root.commands[("podman", "system", "df", "--format", "json")] = output
        assert list(podman.run(make_ctx(root.system()))) == []


def test_non_target_storage_and_small_inventories_are_not_reported(root):
    root.mkdir(podman.ROOT)
    root.commands[("podman", "system", "df", "--format", "json")] = '[{"Type":"Images","RawReclaimable":1}]'
    assert list(podman.run(make_ctx(root.system()))) == []
    root.commands[("podman", "system", "df", "--format", "json")] = '[{"Type":"Images","RawReclaimable":500000000}]'
    root.mounts.append((podman.ROOT, "ext4", "/dev/sdb1"))
    assert list(podman.run(make_ctx(root.system()))) == []


@pytest.mark.parametrize("marker", ["crictl", "config"])
def test_crio_store_does_not_suggest_podman_pruning(root, marker):
    root.mkdir(podman.ROOT)
    root.commands[("podman", "system", "df", "--format", "json")] = '[{"Type":"Images","RawReclaimable":500000000}]'
    if marker == "crictl":
        root.commands[("crictl", "--version")] = "crictl fixture"
    else:
        root.mkdir("/etc/crio")
    system = root.system()
    commands = []
    runner = system._runner

    def record(argv):
        commands.append(list(argv))
        return runner(argv)

    system._runner = record
    assert list(podman.run(make_ctx(system))) == []
    assert not any(cmd[:3] == ["podman", "system", "df"] for cmd in commands)


def test_unsupported_build_cache_row_has_no_system_prune_suggestion(root):
    root.mkdir(podman.ROOT)
    root.commands[("podman", "system", "df", "--format", "json")] = json.dumps([
        {"Type": "Build Cache", "RawReclaimable": 500000000},
    ])
    assert list(podman.run(make_ctx(root.system()))) == []

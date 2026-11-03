import os

from conftest import make_ctx
from whyfull.checks import logs, podlogs
from whyfull.model import CAUTION


def test_pod_logs_are_reported_once_without_following_container_symlinks(root, monkeypatch):
    monkeypatch.setattr(podlogs, "MIN_BYTES", 20000)
    monkeypatch.setattr(logs, "MIN_ROTATED", 20000)
    monkeypatch.setattr(logs, "BIG_ACTIVE", 20000)
    root.write("/var/log/pods/default_api_uid/api/0.log", size=50000)
    root.write("/var/log/pods/default_api_uid/api/0.log.1.gz", size=30000)
    root.mkdir("/var/log/containers")
    os.symlink("../pods/default_api_uid/api/0.log", root.local("/var/log/containers/api.log"))
    root.write("/var/log/other.log", size=40000)
    ctx = make_ctx(root.system())
    finding, = list(podlogs.run(ctx))
    assert "default/api" in finding.title
    assert finding.risk == CAUTION
    assert finding.bytes >= 80000
    assert any("containerLogMaxSize" in line for line in finding.fix)
    assert len(list(logs.run(ctx))) == 1
    assert list(logs.run(ctx))[0].key == "/var/log/other.log"


def test_only_five_largest_pods_are_reported(root, monkeypatch):
    monkeypatch.setattr(podlogs, "MIN_BYTES", 20000)
    for i in range(7):
        root.write("/var/log/pods/ns_pod%d_uid/c/0.log" % i, size=50000 + 10000 * i)
    findings = list(podlogs.run(make_ctx(root.system())))
    assert len(findings) == 5
    assert "pod6" in findings[0].title
    assert "pod2" in findings[-1].title


def test_log_paths_in_suggestions_are_shell_quoted(root, monkeypatch):
    monkeypatch.setattr(podlogs, "MIN_BYTES", 20000)
    root.write("/var/log/pods/ns_pod_uid/container name/0.log", size=50000)
    finding, = list(podlogs.run(make_ctx(root.system())))
    assert "sudo truncate -s 0 '/var/log/pods/ns_pod_uid/container name/0.log'" in finding.fix


def test_small_missing_and_off_target_pods_are_not_reported(root):
    assert list(podlogs.run(make_ctx(root.system()))) == []
    root.write("/var/log/pods/ns_small_uid/c/0.log", size=100)
    root.write("/var/log/pods/ns_other_uid/c/0.log", size=50000)
    root.mounts.append(("/var/log/pods/ns_other_uid", "ext4", "/dev/sdb1"))
    assert list(podlogs.run(make_ctx(root.system()))) == []

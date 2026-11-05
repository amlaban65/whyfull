"""Regression coverage for CI runner workspace disk usage checks."""

from conftest import make_ctx

from whyfull.checks import ci_runners
from whyfull.model import REVIEW


def _findings(root):
    return list(ci_runners.run(make_ctx(root.system())))


def test_github_runner_workspace_includes_tools_once(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 20000)
    root.write("/opt/actions-runner/.runner", "registered")
    root.write("/opt/actions-runner/_work/project/output", size=25000)
    root.write("/opt/actions-runner/_work/_tool/python/3.12", size=30000)

    found = _findings(root)
    assert len(found) == 1
    f = found[0]
    assert f.risk == REVIEW
    assert f.key == "/opt/actions-runner/_work"
    assert "_tool" in f.evidence[1]
    assert "included above" in f.evidence[1]
    assert "! -name _tool" in f.fix[2]
    assert f.bytes >= 55000


def test_github_runner_requires_registration_and_target_filesystem(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 20000)
    root.write("/home/alice/actions-runner/_work/project/cache", size=50000)
    assert _findings(root) == []  # Unregistered directory is not a runner.

    root.write("/home/alice/actions-runner/.runner", "registered")
    root.mounts.append(("/home/alice/actions-runner", "ext4", "/dev/sdb1"))
    assert _findings(root) == []  # Runner data is on a different target device.


def test_github_runner_under_floor_is_ignored(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 100000)
    root.write("/home/runner/actions-runner/.runner", "registered")
    root.write("/home/runner/actions-runner/_work/job/output", size=25000)
    assert _findings(root) == []


def test_gitlab_runner_system_user_builds_and_cache(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 20000)
    passwd = root.local("/etc/passwd")
    with open(passwd, "a") as handle:
        handle.write("gitlab-runner:x:995:995:GitLab Runner:/var/lib/gitlab-runner:/bin/bash\n")
    root.write("/var/lib/gitlab-runner/builds/project/output", size=25000)
    root.write("/var/lib/gitlab-runner/cache/archive.zip", size=26000)

    found = _findings(root)
    assert {f.key for f in found} == {
        "/var/lib/gitlab-runner/builds", "/var/lib/gitlab-runner/cache",
    }
    assert all(f.risk == REVIEW for f in found)
    assert all("Stop GitLab Runner" in f.fix[0] for f in found)


def test_gitlab_docker_cache_volumes(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 20000)
    name = "runner-test-project-1-concurrent-0-cache-example"
    path = "/var/lib/docker/volumes/" + name + "/_data"
    root.write(path + "/cache.bin", size=28000)
    root.commands[("docker", "volume", "ls", "--format", "{{.Name}}")] = (
        "unrelated-volume\n" + name + "\n"
    )
    root.commands[("docker", "volume", "inspect", "--format", "{{.Mountpoint}}", name)] = path + "\n"

    found = _findings(root)
    assert len(found) == 1
    assert found[0].key == "docker:" + name
    assert found[0].risk == REVIEW
    assert "clear-docker-cache" in found[0].fix[0]
    assert "docker volume rm" in found[0].fix[-1]


def test_unreadable_or_missing_docker_is_ignored(root, monkeypatch):
    monkeypatch.setattr(ci_runners, "MIN_BYTES", 20000)
    assert _findings(root) == []

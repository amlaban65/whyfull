"""Check the suggested archive cleanup against real find selection."""

import shlex
import subprocess

from conftest import make_ctx

from whyfull.checks import logs


def test_rotated_cleanup_selects_reported_archives(root, monkeypatch):
    monkeypatch.setattr(logs, "MIN_ROTATED", 1000)
    archives = ["app.log.zip", "app.log.gz", "app.log.xz", "app.log.bz2",
                "app.log.zst", "app.log.old", "app.log.1", "app.log-20261103"]
    active = ["app.log", "app.log.zip.bak", "app.log.1.tmp"]
    for name in archives + active:
        root.write("/var/log/" + name, size=5000)
    found = list(logs.run(make_ctx(root.system())))
    finding, = [f for f in found if f.key == "rotated"]

    command = shlex.split(finding.fix[0])
    assert command[:3] == ["sudo", "find", "/var/log"]
    assert command[-1] == "-delete"
    # Exercise the real selector without sudo or deletion, against fake files only.
    command = ["find", root.local("/var/log")] + command[3:-1] + ["-print"]
    output = subprocess.check_output(command, universal_newlines=True)
    selected = set(output.splitlines())
    assert selected == set(root.local("/var/log/" + name) for name in archives)

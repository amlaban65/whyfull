"""Large kubelet pod logs, without counting /var/log/containers symlinks."""

import os
import shlex

from whyfull.checks import check
from whyfull.checks.logs import walk_logs
from whyfull.model import CAUTION, Finding
from whyfull.units import human
from whyfull.walk import allocated

ROOT = "/var/log/pods"
MIN_BYTES = 500 * 10 ** 6


@check("pod-logs", "Large Kubernetes pod logs")
def run(ctx):
    pods = []
    for name in ctx.system.listdir(ROOT):
        path = os.path.join(ROOT, name)
        if not ctx.on_target(path):
            continue
        files = []
        for log, st in walk_logs(ctx, path):
            basename = os.path.basename(log)
            if basename.endswith(".log") or ".log." in basename:
                files.append((allocated(st), log))
        size = sum(n for n, _ in files)
        if size >= MIN_BYTES:
            pods.append((size, name, path, files))
    pods.sort(reverse=True)
    for size, name, path, files in pods[:5]:
        parts = name.split("_", 2)
        label = "%s/%s" % (parts[0], parts[1]) if len(parts) == 3 else name
        files.sort(reverse=True)
        fixes = [
            "# Set containerLogMaxSize and containerLogMaxFiles in the kubelet configuration.",
            "# Truncating a log loses its history; review the largest files first:",
        ]
        fixes.extend("sudo truncate -s 0 %s" % shlex.quote(log) for _, log in files[:5])
        yield Finding(
            "pod-logs", path, "Kubernetes pod %s logs use %s" % (label, human(size)),
            size, CAUTION, ctx.dev_of(path),
            detail=("Kubelet rotates logs according to containerLogMaxSize and containerLogMaxFiles. "
                    "Check those limits and collect any history you need before truncating a live log. "
                    "The suggested commands cover at most the five largest files, not every file in the pod."),
            fix=fixes,
            evidence=["%s  %s" % (human(n), log) for n, log in files[:5]],
        )

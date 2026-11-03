"""Log files under /var/log: rotated archives and runaway active logs."""

import os
import re
import shlex
import stat as statmod

from whyfull.checks import check
from whyfull.model import CAUTION, REVIEW, Finding
from whyfull.units import human
from whyfull.walk import allocated

ROTATED_RE = re.compile(r"(\.(gz|xz|bz2|zst|zip|old)|\.\d+(\.(gz|xz|bz2|zst))?|-\d{8}(\.(gz|xz|bz2|zst))?)$")
MIN_ROTATED = 200 * 10 ** 6
BIG_ACTIVE = 1 * 10 ** 9
SKIP_DIRS = {"journal", "pods", "containers"}  # handled by dedicated checks; containers are pod-log symlinks


def walk_logs(ctx, root="/var/log"):
    """Yield (display path, stat) for regular files under /var/log on a target device."""
    local_root = ctx.system.path(root)
    stack = [local_root]
    while stack:
        if ctx.budget.expired():
            return
        path = stack.pop()
        try:
            it = os.scandir(path)
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_dev not in ctx.target_devs:
                    continue
                if statmod.S_ISDIR(st.st_mode):
                    if not (path == local_root and entry.name in SKIP_DIRS):
                        stack.append(entry.path)
                elif statmod.S_ISREG(st.st_mode):
                    yield ctx.system.display(entry.path), st


@check("logs", "Large and rotated log files")
def run(ctx):
    rotated = {}  # dev -> [bytes, count, examples]
    big = []
    for path, st in walk_logs(ctx):
        size = allocated(st)
        if ROTATED_RE.search(os.path.basename(path)):
            r = rotated.setdefault(st.st_dev, [0, 0, []])
            r[0] += size
            r[1] += 1
            r[2].append((size, path))
        elif size >= BIG_ACTIVE:
            big.append((size, path, st.st_dev))

    for dev, (nbytes, count, examples) in rotated.items():
        if nbytes < MIN_ROTATED:
            continue
        examples.sort(reverse=True)
        yield Finding(
            "logs", "rotated", "%d rotated or compressed log files in /var/log" % count,
            nbytes, REVIEW, dev,
            detail="Old log archives left behind by logrotate. Keep any you need for audits first.",
            fix=["sudo find /var/log -xdev -type f -regextype posix-extended "
                 "-regex '.*(\\.(gz|xz|bz2|zst|zip|old)|\\.[0-9]+|-[0-9]{8})$' -delete"],
            evidence=["%s  %s" % (human(s), p) for s, p in examples[:5]],
        )

    big.sort(reverse=True)
    for size, path, dev in big[:5]:
        yield Finding(
            "logs", path, "%s is %s" % (path, human(size)), size, CAUTION, dev,
            detail=("An active log this large usually means log rotation isn't set up for it. "
                    "Truncate it rather than deleting it: deleting a file a service still writes "
                    "to doesn't free the space. Then add a logrotate rule."),
            fix=["sudo truncate -s 0 %s" % shlex.quote(path),
                 "# then check /etc/logrotate.d/ has a rule covering %s" % os.path.dirname(path)],
        )

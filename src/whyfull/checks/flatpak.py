"""Flatpak runtimes that no installed app needs any more."""

import os

from whyfull.checks import check
from whyfull.model import SAFE, Finding
from whyfull.units import human

MIN_BYTES = 200 * 10 ** 6
SYSTEM = "/var/lib/flatpak/runtime"
USER_RUNTIME = ".local/share/flatpak/runtime"


@check("flatpak", "Unused Flatpak runtimes")
def run(ctx):
    if not ctx.system.has("flatpak"):
        return
    places = []  # (user or None for the system installation, runtime directory)
    if ctx.system.exists(SYSTEM):
        places.append((None, SYSTEM))
    for user, home in ctx.system.users():
        places.append((user, os.path.join(home, USER_RUNTIME)))

    groups = {}  # dev -> [total bytes, [(size, user, path)]]
    for user, path in places:
        if not ctx.system.exists(path) or not ctx.on_target(path):
            continue
        size = ctx.size(path)
        if size == 0:
            continue
        g = groups.setdefault(ctx.dev_of(path), [0, []])
        g[0] += size
        g[1].append((size, user, path))

    for dev, (total, items) in groups.items():
        if total < MIN_BYTES:
            continue
        items.sort(reverse=True)
        fix = []
        for _size, user, _path in items:
            if user is None:
                fix.append("flatpak uninstall --unused -y")
            elif user == "root":
                fix.append("flatpak uninstall --user --unused -y")
            else:
                fix.append("sudo -u %s -H sh -c 'flatpak uninstall --user --unused -y'" % user)
        yield Finding(
            "flatpak", "runtimes", "Flatpak runtimes", total, SAFE, dev,
            detail=("Runtimes no installed app needs any more. Flatpak downloads them again if needed. "
                    "The total includes runtimes that are still in use; uninstalling only removes the unused ones."),
            fix=fix[:5],
            evidence=["%s  %s" % (human(s), p) for s, _, p in items[:5]],
        )

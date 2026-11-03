"""Flatpak runtimes that no installed app needs any more."""

import os

from whyfull.checks import check
from whyfull.model import SAFE, Finding
from whyfull.units import human

MIN_BYTES = 200 * 10 ** 6
SYSTEM = "/var/lib/flatpak/runtime"
USER_RUNTIME = ".local/share/flatpak/runtime"


def app_runtimes(system, user):
    """Return runtime IDs referenced by apps in one installation, or None on failure."""
    if user is None:
        command = ["flatpak", "--system", "list", "--app", "--columns=runtime"]
    elif user == "root":
        command = ["flatpak", "--user", "list", "--app", "--columns=runtime"]
    else:
        command = ["sudo", "-u", user, "-H", "flatpak", "--user", "list", "--app", "--columns=runtime"]
    output = system.run(command)
    if output is None:
        return None
    lines = output.splitlines()
    if lines and lines[0].strip().lower() == "runtime":
        lines = lines[1:]
    return set(line.strip().split("/", 1)[0] for line in lines if line.strip())


@check("flatpak", "Unused Flatpak runtimes")
def run(ctx):
    if not ctx.system.has("flatpak"):
        return
    places = []  # (user or None for the system installation, runtime directory)
    if ctx.system.exists(SYSTEM):
        places.append((None, SYSTEM))
    for user, home in ctx.system.users():
        places.append((user, os.path.join(home, USER_RUNTIME)))

    # An app in a per-user installation may use a runtime from the system
    # installation. Take the union across installations before estimating any
    # directory, and fail closed if any user's app list cannot be read.
    used = set()
    for user, _path in places:
        runtimes = app_runtimes(ctx.system, user)
        if runtimes is None:
            return
        used.update(runtimes)

    groups = {}  # dev -> [total bytes, [(size, user, path)]]
    for user, path in places:
        if not ctx.system.exists(path) or not ctx.on_target(path):
            continue
        for runtime in ctx.system.listdir(path):
            if runtime in used:
                continue
            runtime_path = os.path.join(path, runtime)
            size = ctx.size(runtime_path)
            if size == 0:
                continue
            g = groups.setdefault(ctx.dev_of(runtime_path), [0, []])
            g[0] += size
            g[1].append((size, user, runtime_path))

    for dev, (total, items) in groups.items():
        if total < MIN_BYTES:
            continue
        items.sort(key=lambda item: item[0], reverse=True)
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
            detail=("Runtimes whose IDs are not referenced by installed apps in this installation. "
                    "Flatpak downloads them again if needed. Variants sharing an ID are treated as in use "
                    "when any branch is used."),
            fix=fix[:5],
            evidence=["%s  %s" % (human(s), p) for s, _, p in items[:5]],
        )

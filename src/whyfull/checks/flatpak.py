"""Flatpak runtimes that no installed app needs any more."""

import os

from whyfull.checks import check
from whyfull.model import SAFE, Finding
from whyfull.units import human

MIN_BYTES = 200 * 10 ** 6
SYSTEM = "/var/lib/flatpak/runtime"
USER_RUNTIME = ".local/share/flatpak/runtime"
SYSTEM_APPS = "/var/lib/flatpak/app"
USER_APPS = ".local/share/flatpak/app"


def app_runtimes(system, apps_path):
    """Return runtime IDs read from installed app metadata, or None if it is incomplete."""
    if not system.exists(apps_path):
        return set()
    used = set()
    for app in system.listdir(apps_path):
        metadata = os.path.join(apps_path, app, "current", "active", "metadata")
        if not system.exists(metadata):
            return None
        text = system.read_text(metadata)
        if text is None:
            return None
        in_application = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_application = line[1:-1] == "Application"
            elif in_application and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() == "runtime" and value.strip():
                    used.add(value.strip().split("/", 1)[0])
                    break
    return used


@check("flatpak", "Unused Flatpak runtimes")
def run(ctx):
    if not ctx.system.has("flatpak"):
        return
    places = []  # (user or None for the system installation, runtime directory, apps directory)
    if ctx.system.exists(SYSTEM) or ctx.system.exists(SYSTEM_APPS):
        places.append((None, SYSTEM, SYSTEM_APPS))
    for user, home in ctx.system.users():
        runtime_path = os.path.join(home, USER_RUNTIME)
        apps_path = os.path.join(home, USER_APPS)
        if ctx.system.exists(runtime_path) or ctx.system.exists(apps_path):
            places.append((user, runtime_path, apps_path))

    # An app in one installation may use a runtime from another. Read only the
    # metadata files and take the union before estimating reclaimable space.
    used = set()
    for _user, _path, apps_path in places:
        runtimes = app_runtimes(ctx.system, apps_path)
        if runtimes is None:
            ctx.note("Could not read Flatpak app metadata; unused-runtime estimates were skipped.")
            return
        used.update(runtimes)

    groups = {}  # dev -> [total bytes, [(size, user, path)]]
    for user, path, _apps_path in places:
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
                command = "flatpak uninstall --unused -y"
            elif user == "root":
                command = "flatpak uninstall --user --unused -y"
            else:
                command = "sudo -u %s -H sh -c 'flatpak uninstall --user --unused -y'" % user
            if command not in fix:
                fix.append(command)
        yield Finding(
            "flatpak", "runtimes", "Flatpak runtimes", total, SAFE, dev,
            detail=("Runtimes whose IDs are not referenced by installed apps in this installation. "
                    "Flatpak downloads them again if needed. Variants sharing an ID are treated as in use "
                    "when any branch is used."),
            fix=fix[:5],
            evidence=["%s  %s" % (human(s), p) for s, _, p in items[:5]],
        )

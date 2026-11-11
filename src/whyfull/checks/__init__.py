"""Checks find specific, explainable causes of disk usage.

A check is a function decorated with @check. It receives a Context and
returns (or yields) Finding objects. Checks must never modify the system:
they read files and run read-only commands only.

To add one, create a module in this package, decorate a function with
@check("my-id", "What it looks for"), and add the module name to MODULES
below. See CONTRIBUTING.md for the full walkthrough.
"""

import importlib

from whyfull.walk import du

REGISTRY = []

MODULES = [
    "deleted_open",
    "space",
    "journald",
    "logs",
    "podlogs",
    "containers",
    "cri",
    "podman",
    "packages",
    "kernels",
    "snaps",
    "flatpak",
    "crashes",
    "mysql",
    "searchdata",
    "postgresql",
    "tmpfiles",
    "usercaches",
    "android",
    "jenkins",
    "libvirt",
]


class Check(object):
    def __init__(self, id, title, fn):
        self.id = id
        self.title = title
        self.fn = fn


def check(id, title):
    def register(fn):
        REGISTRY.append(Check(id, title, fn))
        return fn
    return register


def load():
    for name in MODULES:
        importlib.import_module("whyfull.checks." + name)
    return list(REGISTRY)


class Context(object):
    """What a check gets to work with.

    system   -- whyfull.system.System; use it for every file and command access
    targets  -- the Filesystem objects being analysed
    budget   -- shared time budget for size measurements
    """

    def __init__(self, system, targets, budget, all_filesystems=None):
        self.system = system
        self.targets = targets
        self.budget = budget
        self.all_filesystems = all_filesystems or targets
        self.target_devs = set(fs.dev for fs in targets)
        self.notes = []
        self.deleted_open_bytes = {}  # dev -> bytes, filled by the deleted_open check
        self._seen = set()

    def dev_of(self, path):
        st = self.system.lstat(path)
        return None if st is None else st.st_dev

    def on_target(self, path):
        return self.dev_of(path) in self.target_devs

    def size(self, path):
        """Allocated bytes under path (on its own filesystem), or 0 if missing."""
        local = self.system.path(path)
        usage = du(local, budget=self.budget)
        return usage.bytes

    def filesystem(self, dev):
        for fs in self.all_filesystems:
            if fs.dev == dev:
                return fs
        return None

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

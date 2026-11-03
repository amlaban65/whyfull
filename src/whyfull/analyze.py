"""Run the checks against the chosen filesystems and assemble a report."""

import os

from whyfull import __version__
from whyfull.checks import Context, load
from whyfull.model import CAUTION, INFO, REVIEW, SAFE, Finding
from whyfull.mounts import containing, filesystems
from whyfull.units import human
from whyfull.walk import Budget, scan

DEFAULT_THRESHOLD = 85.0


class Target(object):
    """One filesystem under analysis and everything found about it."""

    def __init__(self, fs):
        self.fs = fs
        self.findings = []
        self.tree = None
        self.largest = []  # [(display path, bytes, [(child path, bytes)])]
        self.crowded = []  # [(entries, display path)]

    def reclaimable(self):
        out = {SAFE: 0, REVIEW: 0, CAUTION: 0}
        for f in self.findings:
            if f.risk in out:
                out[f.risk] += f.bytes
        out["total"] = out[SAFE] + out[REVIEW] + out[CAUTION]
        return out

    def largest_dirs(self, system, top=6, children=3, min_share=0.01):
        """[(display path, bytes, [(child display path, bytes)])] from the scan."""
        if self.tree is None:
            return []
        root = system.path(self.fs.mountpoint).rstrip("/") or "/"
        floor = self.fs.used * min_share

        def kids(parent):
            out = [(p, b) for p, b in self.tree.sizes.items()
                   if os.path.dirname(p) == parent and p != parent and b >= floor]
            return sorted(out, key=lambda pb: -pb[1])

        result = []
        for path, nbytes in kids(root)[:top]:
            sub = [(system.display(p), b) for p, b in kids(path)[:children]]
            result.append((system.display(path), nbytes, sub))
        return result


class Report(object):
    def __init__(self):
        self.version = __version__
        self.filesystems = []
        self.targets = []
        self.threshold = DEFAULT_THRESHOLD
        self.all_clear = False  # no filesystem above the threshold
        self.notes = []
        self.errors = []  # (check id, message)


def choose_targets(system, all_fs, paths, threshold):
    if paths:
        chosen = []
        for p in paths:
            fs = containing(system, os.path.abspath(p) if system.root == "/" else p)
            if fs is None:
                raise ValueError("can't find the filesystem for %s" % p)
            if fs.dev not in [t.dev for t in chosen]:
                chosen.append(fs)
        return chosen, False
    full = [fs for fs in all_fs if fs.percent >= threshold]
    if full:
        return sorted(full, key=lambda f: -f.percent), False
    root = containing(system, "/", all_fs) or containing(system, "/")
    return ([root] if root else []), True


def analyze(system, paths=None, threshold=DEFAULT_THRESHOLD, scan_seconds=30, check_seconds=60,
            only=None, skip=None, do_scan=True, exclude=None):
    report = Report()
    report.threshold = threshold
    all_fs = filesystems(system)
    report.filesystems = all_fs
    targets, report.all_clear = choose_targets(system, all_fs, paths, threshold)
    report.targets = [Target(fs) for fs in targets]
    if not targets:
        return report

    known = {fs.dev: fs for fs in all_fs}
    for fs in targets:
        known.setdefault(fs.dev, fs)
    ctx = Context(system, targets, Budget(check_seconds), list(known.values()))

    for chk in load():
        if only and chk.id not in only:
            continue
        if skip and chk.id in skip:
            continue
        try:
            found = list(chk.fn(ctx) or [])
        except Exception as e:  # a broken check must never hide the others
            report.errors.append((chk.id, "%s: %s" % (type(e).__name__, e)))
            continue
        by_dev = {t.fs.dev: t for t in report.targets}
        for f in found:
            t = by_dev.get(f.dev)
            if t is not None and (f.bytes > 0 or f.risk == INFO):
                t.findings.append(f)
    if ctx.budget.hit:
        ctx.note("Some checks hit their time limit; sizes may be understated.")

    excluded = [system.path(os.path.abspath(p) if system.root == "/" else p) for p in (exclude or [])]
    if do_scan and excluded:
        ctx.note("Excluded paths are omitted from scan totals and largest directories: %s. "
                 "The unexplained-space check is skipped because the scan omits these paths; "
                 "targeted checks still run there." % ", ".join(exclude))

    for t in report.targets:
        if do_scan:
            t.tree = scan(system.path(t.fs.mountpoint), t.fs.dev, Budget(scan_seconds), exclude=excluded)
            if not t.tree.complete:
                ctx.note("The scan of %s stopped at its time limit; raise it with --scan-time." % t.fs.mountpoint)
            if t.tree.denied and not system.is_root:
                ctx.note("%d directories on %s couldn't be read; run with sudo for a complete picture."
                         % (t.tree.denied, t.fs.mountpoint))
            t.largest = t.largest_dirs(system)
            t.crowded = [(n, system.display(p)) for n, p in t.tree.crowded]
            gap = None if excluded else unexplained(system, t, ctx.deleted_open_bytes.get(t.fs.dev, 0), all_fs)
            if gap is not None:
                t.findings.append(gap)
        t.findings.sort(key=lambda f: (-f.priority, -f.bytes))

    report.notes = ctx.notes
    return report


def unexplained(system, target, deleted_open, all_fs):
    """An INFO finding when df's 'used' is far above what the files add up to."""
    tree, fs = target.tree, target.fs
    if tree is None or not tree.complete or tree.denied:
        return None
    gap = fs.used - tree.total - deleted_open
    if gap < max(512 * 2 ** 20, 0.05 * fs.used):
        return None
    root = fs.mountpoint.rstrip("/")
    covering = sorted(m.mountpoint for m in all_fs
                      if m.dev != fs.dev and m.mountpoint != fs.mountpoint
                      and (m.mountpoint + "/").startswith(root + "/"))
    fix = []
    if covering:
        fix = ["sudo mkdir -p /mnt/whyfull-under && sudo mount --bind %s /mnt/whyfull-under" % fs.mountpoint]
        fix += ["sudo du -sh /mnt/whyfull-under%s" % m[len(root):] for m in covering[:6]]
        fix += ["sudo umount /mnt/whyfull-under"]
    if fs.fstype == "btrfs":
        fix += ["sudo btrfs subvolume list -s %s  # snapshots keep deleted data" % fs.mountpoint]
    if fs.fstype == "zfs":
        fix += ["zfs list -t snapshot -o name,used -s used"]
    causes = []
    if covering:
        causes.append("files written into a directory before another disk was mounted over it "
                      "(%s): they still use space but are hidden" % ", ".join(covering[:4]))
    if fs.fstype in ("btrfs", "zfs"):
        causes.append("snapshots holding on to deleted data")
    causes.append("filesystem metadata and journal")
    return Finding(
        "unexplained", fs.mountpoint,
        "%s in use on %s isn't in any file whyfull can see" % (human(gap), fs.mountpoint),
        gap, INFO, fs.dev, priority=10,
        detail="Likely causes: " + "; ".join(causes) + ".",
        fix=fix,
    )

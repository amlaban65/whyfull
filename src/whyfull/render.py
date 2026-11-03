"""Turn a Report into text, JSON or Markdown."""

import json
import textwrap

from whyfull.model import CAUTION, INFO, REVIEW, SAFE
from whyfull.units import human

RISK_LABEL = {SAFE: "safe", REVIEW: "review", CAUTION: "caution", INFO: "info"}


class Style(object):
    def __init__(self, color):
        on = bool(color)
        self.bold = "\033[1m" if on else ""
        self.dim = "\033[2m" if on else ""
        self.red = "\033[31m" if on else ""
        self.green = "\033[32m" if on else ""
        self.yellow = "\033[33m" if on else ""
        self.cyan = "\033[36m" if on else ""
        self.reset = "\033[0m" if on else ""

    def risk(self, risk):
        return {SAFE: self.green, REVIEW: self.yellow, CAUTION: self.red, INFO: self.cyan}.get(risk, "")

    def pct(self, percent):
        if percent >= 95:
            return self.red + self.bold
        if percent >= 85:
            return self.yellow
        return ""


def _headline(fs):
    return "%s is %d%% full · %s used of %s · %s free" % (
        fs.mountpoint, fs.percent, human(fs.used), human(fs.size), human(fs.avail))


def text(report, color=False, verbose=False, width=100):
    s = Style(color)
    out = []
    w = out.append

    if len(report.filesystems) > 1 or report.all_clear:
        w("%sFilesystems%s" % (s.bold, s.reset))
        target_devs = set(t.fs.dev for t in report.targets)
        for fs in report.filesystems:
            mark = "›" if fs.dev in target_devs else " "
            w("  %s %s%3d%%%s  %-24s %9s of %-9s %s%s%s" % (
                mark, s.pct(fs.percent), fs.percent, s.reset, fs.mountpoint, human(fs.used),
                human(fs.size), s.dim, fs.fstype, s.reset))
        w("")
    if report.all_clear and report.targets:
        w("%sNo filesystem is above %d%% full.%s Here's what uses space on %s anyway." % (
            s.green, report.threshold, s.reset, report.targets[0].fs.mountpoint))
        w("")

    for t in report.targets:
        fs = t.fs
        w("%s%s%s%s  %s(%s on %s)%s" % (s.bold, s.pct(fs.percent), _headline(fs), s.reset,
                                       s.dim, fs.fstype, fs.source, s.reset))
        if fs.inodes and fs.inode_percent >= 50:
            w("%sinodes: %.0f%% used%s" % (s.dim, fs.inode_percent, s.reset))
        w("")

        if not t.findings:
            w("  Nothing specific found. See the largest directories below.")
            w("")
        for f in t.findings:
            size = human(f.bytes) if f.bytes else ""
            label = RISK_LABEL[f.risk]
            w("%10s  %s%-7s%s  %s%s%s" % (size, s.risk(f.risk), label, s.reset, s.bold, f.title, s.reset))
            pad = " " * 21
            if f.detail and (verbose or f.risk == INFO):
                for line in textwrap.wrap(f.detail, max(40, width - len(pad))):
                    w(pad + s.dim + line + s.reset)
            for e in f.evidence[: (8 if verbose else 3)]:
                w(pad + s.dim + e + s.reset)
            if len(f.evidence) > 3 and not verbose:
                w(pad + s.dim + "... and %d more (-v to list)" % (len(f.evidence) - 3) + s.reset)
            for cmd in f.fix:
                if cmd.startswith("#"):
                    w(pad + s.dim + cmd + s.reset)
                else:
                    w(pad + s.cyan + "$ " + s.reset + cmd)
            w("")

        r = t.reclaimable()
        if r["total"]:
            parts = []
            for risk in (SAFE, REVIEW, CAUTION):
                if r[risk]:
                    parts.append("%s%s %s%s" % (s.risk(risk), human(r[risk]), risk, s.reset))
            share = 100.0 * r["total"] / fs.used if fs.used else 0
            w("%sYou can free about %s (%.0f%% of what's used):%s %s" % (
                s.bold, human(r["total"]), share, s.reset, " · ".join(parts)))
            w("")

        dirs = t.largest
        if dirs:
            w("%sLargest directories on %s%s" % (s.bold, fs.mountpoint, s.reset))
            for path, nbytes, kids in dirs:
                w("  %9s  %s" % (human(nbytes), path))
                for kpath, kbytes in kids:
                    w("  %9s    %s%s%s" % (human(kbytes), s.dim, kpath, s.reset))
            w("")

        crowded = t.crowded
        if crowded and any(f.check == "inodes" for f in t.findings):
            w("%sCrowded directories (most entries)%s" % (s.bold, s.reset))
            for count, path in crowded[:5]:
                w("  %11s  %s" % ("{:,}".format(count), path))
            w("")

    for note in report.notes:
        w("%snote: %s%s" % (s.dim, note, s.reset))
    for check_id, msg in report.errors:
        w("%serror in check %s: %s (please report this)%s" % (s.red, check_id, msg, s.reset))
    if report.notes or report.errors:
        w("")
    w("%swhyfull %s never deletes anything. Review each command before you run it.%s" % (
        s.dim, report.version, s.reset))
    return "\n".join(out) + "\n"


def to_dict(report, system):
    targets = []
    for t in report.targets:
        r = t.reclaimable()
        targets.append({
            "filesystem": t.fs.to_dict(),
            "reclaimable": r,
            "findings": [f.to_dict() for f in t.findings],
            "largest_dirs": [
                {"path": p, "bytes": b, "children": [{"path": cp, "bytes": cb} for cp, cb in kids]}
                for p, b, kids in t.largest
            ],
            "scan": None if t.tree is None else {
                "complete": t.tree.complete, "unreadable_dirs": t.tree.denied,
                "bytes_seen": t.tree.total, "files_seen": t.tree.files,
            },
        })
    return {
        "version": report.version,
        "threshold": report.threshold,
        "all_clear": report.all_clear,
        "filesystems": [fs.to_dict() for fs in report.filesystems],
        "targets": targets,
        "notes": report.notes,
        "errors": [{"check": c, "message": m} for c, m in report.errors],
    }


def as_json(report, system):
    return json.dumps(to_dict(report, system), indent=2) + "\n"


def markdown(report, verbose=False):
    out = []
    w = out.append
    for t in report.targets:
        fs = t.fs
        w("### %s" % _headline(fs))
        w("")
        w("`%s` on `%s`%s" % (fs.fstype, fs.source,
                               ", inodes %.0f%% used" % fs.inode_percent if fs.inode_percent >= 50 else ""))
        w("")
        if t.findings:
            w("| Size | Risk | What | Fix |")
            w("|--:|---|---|---|")
            for f in t.findings:
                cmds = [c for c in f.fix if not c.startswith("#")]
                fix = "<br>".join("`%s`" % c.replace("|", "\\|") for c in cmds[:3]) or "–"
                w("| %s | %s | %s | %s |" % (human(f.bytes) if f.bytes else "", f.risk,
                                             f.title.replace("|", "\\|"), fix))
            w("")
        r = t.reclaimable()
        if r["total"]:
            w("About **%s** can be freed (%s safe, %s review, %s caution)." % (
                human(r["total"]), human(r[SAFE]), human(r[REVIEW]), human(r[CAUTION])))
            w("")
        dirs = t.largest
        if dirs:
            w("<details><summary>Largest directories</summary>")
            w("")
            for path, nbytes, kids in dirs:
                w("- %s `%s`" % (human(nbytes), path))
                for kp, kb in kids:
                    w("  - %s `%s`" % (human(kb), kp))
            w("")
            w("</details>")
            w("")
    for note in report.notes:
        w("Note: %s" % note)
        w("")
    w("<sub>Generated by [whyfull](https://github.com/amlaban65/whyfull) %s</sub>" % report.version)
    return "\n".join(out) + "\n"

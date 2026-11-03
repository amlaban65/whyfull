"""Command-line interface."""

import argparse
import os
import sys

from whyfull import __version__
from whyfull.analyze import DEFAULT_THRESHOLD, analyze
from whyfull.checks import load
from whyfull.render import as_json, markdown, text
from whyfull.system import System
from whyfull.units import parse_threshold

DESCRIPTION = """\
Find out why a Linux disk is full and how to safely free space.

whyfull looks for the usual suspects (deleted files still held open, the
systemd journal, Docker build cache and images, old kernels, package and
build caches, core dumps, runaway logs, inode exhaustion) and prints the
command that fixes each one. It never deletes anything itself.
"""

EPILOG = """\
examples:
  sudo whyfull                 analyse every filesystem that is %(t)d%%+ full
  sudo whyfull /var            analyse the filesystem holding /var
  whyfull --format markdown    paste into an incident ticket
  whyfull --fail-above 90      exit 1 if any filesystem is 90%%+ full (for cron)

run with sudo: without it, files owned by other users and services can't be measured.
""" % {"t": DEFAULT_THRESHOLD}


def build_parser():
    p = argparse.ArgumentParser(
        prog="whyfull", description=DESCRIPTION, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("paths", nargs="*", metavar="PATH",
                   help="analyse the filesystem holding PATH (default: every filesystem above --threshold)")
    p.add_argument("-t", "--threshold", default=str(int(DEFAULT_THRESHOLD)), metavar="PCT",
                   help="how full a filesystem must be to be analysed when no PATH is given (default %(default)s)")
    p.add_argument("-f", "--format", choices=["text", "json", "markdown"], default="text")
    p.add_argument("--json", dest="format", action="store_const", const="json", help="same as --format json")
    p.add_argument("-v", "--verbose", action="store_true", help="explain every finding and list more evidence")
    p.add_argument("--scan-time", type=float, default=30, metavar="SEC",
                   help="time limit for scanning the whole filesystem, 0 for none (default %(default)s)")
    p.add_argument("--no-scan", action="store_true", help="skip the full scan; run only the targeted checks")
    p.add_argument("--exclude", action="append", default=[], metavar="PATH",
                   help="omit PATH from the full scan (repeatable); targeted checks still run there")
    p.add_argument("--only", metavar="CHECKS", help="comma-separated checks to run (see --list-checks)")
    p.add_argument("--skip", metavar="CHECKS", help="comma-separated checks to skip")
    p.add_argument("--list-checks", action="store_true", help="list the checks and exit")
    p.add_argument("--fail-above", metavar="PCT",
                   help="exit with status 1 if any filesystem is at least PCT full")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.add_argument("--version", action="version", version="whyfull " + __version__)
    # For tests and for inspecting a mounted image: treat DIR as /.
    p.add_argument("--root", default="/", help=argparse.SUPPRESS)
    return p


def _split(value):
    return set(v.strip() for v in value.split(",") if v.strip()) if value else None


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_checks:
        for chk in load():
            print("%-14s %s" % (chk.id, chk.title))
        return 0

    try:
        threshold = parse_threshold(args.threshold)
        fail_above = parse_threshold(args.fail_above) if args.fail_above else None
    except ValueError as e:
        print("whyfull: %s" % e, file=sys.stderr)
        return 2

    known = set(c.id for c in load())
    only, skip = _split(args.only), _split(args.skip)
    unknown = ((only or set()) | (skip or set())) - known
    if unknown:
        print("whyfull: unknown check(s): %s (see --list-checks)" % ", ".join(sorted(unknown)), file=sys.stderr)
        return 2

    if not sys.platform.startswith("linux") and args.root == "/":
        print("whyfull: only Linux is supported", file=sys.stderr)
        return 2

    system = System(root=args.root)
    try:
        report = analyze(system, paths=args.paths or None, threshold=threshold,
                         scan_seconds=args.scan_time or None, only=only, skip=skip,
                         do_scan=not args.no_scan, exclude=args.exclude)
    except ValueError as e:
        print("whyfull: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    if args.format == "json":
        sys.stdout.write(as_json(report, system))
    elif args.format == "markdown":
        sys.stdout.write(markdown(report, verbose=args.verbose))
    else:
        color = args.color == "always" or (
            args.color == "auto" and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
            and os.environ.get("TERM") != "dumb")
        width = _terminal_width()
        sys.stdout.write(text(report, color=color, verbose=args.verbose, width=width))

    if fail_above is not None and any(fs.percent >= fail_above for fs in report.filesystems):
        return 1
    return 0


def _terminal_width():
    try:
        return max(60, min(120, os.get_terminal_size().columns))
    except OSError:
        return 100


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

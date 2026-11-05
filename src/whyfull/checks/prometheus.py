"""Informational Prometheus TSDB measurements; never change live data."""

import shlex
import stat

from whyfull.checks import check
from whyfull.model import INFO, Finding

MIN_BYTES = 5 * 10 ** 9
LARGE_WAL = 3 * 10 ** 9
PATHS = ("/var/lib/prometheus", "/var/lib/prometheus/metrics2")


def directory(ctx, path):
    info = ctx.system.lstat(path)
    return info if info is not None and stat.S_ISDIR(info.st_mode) else None


@check("prometheus", "Prometheus TSDB data and WAL")
def run(ctx):
    seen = []
    for path in PATHS:
        info = directory(ctx, path)
        if info is None or not ctx.on_target(path):
            continue
        if any(path.startswith(parent + "/") and info.st_dev == dev for parent, dev in seen):
            continue
        wal = directory(ctx, path + "/wal")
        head = directory(ctx, path + "/chunks_head")
        if wal is None and head is None:
            continue
        seen.append((path, info.st_dev))
        size = ctx.size(path)
        if size < MIN_BYTES:
            continue
        detail = ("Measured TSDB data size, not reclaimable space. Never delete blocks or WAL files by hand. "
                  "Review retention and high-cardinality series. Size retention deletes persistent blocks only; "
                  "active WAL and chunks_head still need space, as does compaction.")
        if wal is not None and wal.st_dev == info.st_dev:
            wal_size = ctx.size(path + "/wal")
            detail += " WAL: %d bytes, included in the total above." % wal_size
            if wal_size >= LARGE_WAL:
                detail += (" Large WAL: review ingestion and head compaction; size alone does not prove a problem. "
                           "Busy servers can legitimately retain several WAL segments.")
        else:
            detail += " WAL was not measured separately (missing, symlink, non-directory or another filesystem)."
        yield Finding(
            "prometheus", path, "Prometheus data in %s" % path, size, INFO, info.st_dev,
            detail=detail,
            fix=[
                "# Inspect persisted block cardinality with the matching Prometheus promtool version:",
                "promtool tsdb analyze %s" % shlex.quote(path),
                "# Review --storage.tsdb.retention.time and --storage.tsdb.retention.size in service configuration.",
                "# Choose a size budget leaving headroom for WAL, chunks_head and compaction; 50GB is only an example.",
                "# Example configuration flag: --storage.tsdb.retention.size=50GB",
            ],
            evidence=[path],
        )

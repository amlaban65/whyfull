"""MySQL and MariaDB binary logs."""

import re
import stat

from whyfull.checks import check
from whyfull.model import REVIEW, Finding
from whyfull.walk import allocated

MIN_BYTES = 10 ** 9
BINLOG = re.compile(r"(?:binlog|.+-bin)\.[0-9]+\Z")


@check("mysql", "MySQL and MariaDB binary logs")
def run(ctx):
    for directory in ("/var/lib/mysql", "/var/lib/mysqld"):
        if not ctx.system.exists(directory):
            continue
        logs = []
        for name in ctx.system.listdir(directory):
            if not BINLOG.match(name):
                continue
            path = directory + "/" + name
            info = ctx.system.lstat(path)
            if info is not None and stat.S_ISREG(info.st_mode) and ctx.on_target(path):
                logs.append((path, allocated(info), info.st_dev))
        by_device = {}
        for path, size, dev in logs:
            by_device.setdefault(dev, []).append((path, size))
        for dev, files in sorted(by_device.items()):
            total = sum(size for _, size in files)
            if total < MIN_BYTES:
                continue
            yield Finding(
                "mysql", directory, "MySQL binary logs in %s" % directory, total, REVIEW, dev,
                detail=("Binary logs may still be needed by replicas or for point-in-time recovery. "
                        "Check replication and backup requirements before purging; never delete them by hand."),
                fix=[
                    "# Check replicas and backups before purging logs older than three days.",
                    'sudo mysql -e "PURGE BINARY LOGS BEFORE NOW() - INTERVAL 3 DAY;"',
                    "# Configure binlog_expire_logs_seconds (MySQL 8) or expire_logs_days (MariaDB).",
                ],
                evidence=[path for path, _ in files[:5]],
            )

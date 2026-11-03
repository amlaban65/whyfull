---
title: MySQL binary logs filling the disk? Purge them safely
description: /var/lib/mysql full of binlog.000123 files? See how much space MySQL and MariaDB binary logs use, purge them without breaking replication or backups, and set an expiry so they stop piling up.
short: Purge binlogs with SQL, never with rm.
---

MySQL writes every change to its binary logs: files named `binlog.000001`, `binlog.000002` and so on (or `mysql-bin.000001` on many setups) in the data directory, usually `/var/lib/mysql`. Replicas read them to stay in sync, and backups use them for point-in-time recovery. On a busy server they add up to tens of GB, and if nothing expires them, they fill the disk.

The one rule: **never delete binary log files with `rm`.** MySQL keeps a list of them in an index file (`binlog.index`). Delete files behind its back and the index points at files that don't exist, which breaks replication and can stop the server from starting cleanly. Purge them with SQL instead.

## See how much space they use

```sh
sudo du -ch /var/lib/mysql/*bin.0* | tail -1
```

Or ask MySQL, which lists each file and its size:

```sh
sudo mysql -e "SHOW BINARY LOGS;"
```

## Check what still needs them

Before purging, make sure nothing still needs the logs you're about to remove.

**Replicas.** On each replica, find the file it is currently reading from the source:

```sh
sudo mysql -e "SHOW REPLICA STATUS\G" | grep Source_Log_File
```

On MySQL older than 8.0.22 and on MariaDB, use `SHOW SLAVE STATUS\G` and look at `Master_Log_File`. Keep that file and everything after it. A replica that is stopped or disconnected still needs its logs when it comes back, so check every replica, not just the running ones.

**Backups.** If you restore by replaying binary logs on top of a backup (point-in-time recovery), keep every log since your oldest backup that you might restore.

## Purge old logs

Remove logs older than a point in time:

```sh
sudo mysql -e "PURGE BINARY LOGS BEFORE NOW() - INTERVAL 3 DAY;"
```

Or remove every log before a specific file, which keeps that file:

```sh
sudo mysql -e "PURGE BINARY LOGS TO 'binlog.000142';"
```

MySQL updates the index file and deletes the files itself. A log that a connected replica is still reading is not removed.

## Stop them piling up again

Set how long binary logs are kept. On MySQL 8, the setting is `binlog_expire_logs_seconds` (the default is 30 days). For three days, add this to the `[mysqld]` section of your config, for example `/etc/mysql/mysql.conf.d/mysqld.cnf`:

```ini
binlog_expire_logs_seconds = 259200
```

MySQL 8 can also apply it without a restart, and keep it across restarts:

```sh
sudo mysql -e "SET PERSIST binlog_expire_logs_seconds = 259200;"
```

On MariaDB, use `expire_logs_days = 3` (newer versions also accept `binlog_expire_logs_seconds`). Older MariaDB versions default to keeping binary logs forever, so this setting matters there.

## If you don't need binary logs at all

A standalone server with no replicas, whose backups don't rely on binary logs, doesn't need them. MySQL 8 turns them on by default. To turn them off, add `disable_log_bin` to `[mysqld]` and restart MySQL. Think twice before doing this on anything you might later want to replicate or restore to a point in time.

## Relay logs on replicas

Replicas keep relay logs (`*-relay-bin.000123`) as well. MySQL deletes each one after applying it, as long as `relay_log_purge` is on, which is the default. If they're piling up, the replica is usually stopped or far behind. Check `SHOW REPLICA STATUS\G` instead of deleting them.

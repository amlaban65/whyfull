import os
import shlex
import subprocess
import sys

import pytest

from conftest import make_ctx

from whyfull.checks import containers, crashes, deleted_open, journald, kernels, logs, packages, snaps
from whyfull.checks import mysql, postgresql, space, tmpfiles, usercaches
from whyfull.model import CAUTION, INFO, REVIEW, SAFE, Filesystem
from whyfull.system import System


def findings(fn, ctx):
    return list(fn(ctx) or [])


def _proc_pid_namespace_aligned():
    """True when /proc PIDs match this process's PID namespace."""
    try:
        return os.readlink("/proc/self") == str(os.getpid())
    except OSError:
        return False


def _proc_pids_holding_deleted(path):
    """PIDs under /proc that still hold a deleted open of `path`."""
    needle = path + " (deleted)"
    held = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return held
    for pid in pids:
        fd_dir = os.path.join("/proc", pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(fd_dir, fd)) == needle:
                    held.append(pid)
                    break
            except OSError:
                continue
    return held


def test_deleted_open_file_held_by_a_real_process(tmp_path):
    path = tmp_path / "app.log"
    with open(str(path), "wb") as f:
        f.write(os.urandom(3 * 1024 * 1024))
    holder = subprocess.Popen([
        sys.executable, "-c",
        "import os,sys,time\n"
        "f=open(sys.argv[1],'rb'); os.unlink(sys.argv[1]); print('ready',flush=True); time.sleep(60)",
        str(path)], stdout=subprocess.PIPE)
    try:
        assert holder.stdout.readline().strip() == b"ready"
        # In some containers/sandboxes /proc is another PID namespace, so
        # subprocess.Popen's PID is not the one listed under /proc.
        proc_pids = _proc_pids_holding_deleted(str(path))
        if not proc_pids:
            if not _proc_pid_namespace_aligned():
                pytest.skip(
                    "helper not visible in /proc (PID namespace mismatch); "
                    "os.readlink('/proc/self') != str(os.getpid())"
                )
            pytest.fail("helper process has no deleted-open fd under /proc")
        system = System()
        dev = os.stat(str(tmp_path)).st_dev
        fs = Filesystem("/", "/dev/x", "ext4", dev, 100, 90, 10)
        from whyfull.checks import Context
        from whyfull.walk import Budget
        ctx = Context(system, [fs], Budget(30))
        found = [f for f in findings(deleted_open.run, ctx) if str(path) + " (deleted)" in f.evidence]
        assert len(found) == 1
        f = found[0]
        assert f.risk == CAUTION
        assert f.bytes >= 3 * 1024 * 1024
        # Assert against the /proc PID that holds the file, not subprocess's
        # host-namespace PID — those differ when /proc is namespaced. Other
        # same-comm processes may share the finding's truncate list; only
        # require our holder to appear.
        assert any(
            any("/proc/%s/fd/" % pid in c for pid in proc_pids)
            for c in f.fix
        )
        assert ctx.deleted_open_bytes[dev] >= 3 * 1024 * 1024
    finally:
        holder.kill()
        holder.wait()


def test_owner_of_maps_cgroups_to_units_and_containers(tmp_path):
    proc = tmp_path / "proc"
    for pid, cgroup, comm in [
        ("10", "0::/system.slice/nginx.service\n", "nginx"),
        ("11", "0::/system.slice/docker-0123456789abcdef0123.scope\n", "node"),
        ("12", "0::/user.slice/user-1000.slice/user@1000.service/app.slice\n", "python3"),
    ]:
        (proc / pid).mkdir(parents=True)
        (proc / pid / "cgroup").write_text(cgroup)
        (proc / pid / "comm").write_text(comm + "\n")
    assert deleted_open.owner_of(str(proc), "10") == ("unit", "nginx.service")
    assert deleted_open.owner_of(str(proc), "11") == ("container", "0123456789ab")
    assert deleted_open.owner_of(str(proc), "12") == ("process", "python3")


def test_journald(root, monkeypatch):
    monkeypatch.setattr(journald, "KEEP", 1000)
    monkeypatch.setattr(journald, "MIN_RECLAIM", 1000)
    root.write("/var/log/journal/abc/system.journal", size=200000)
    f, = findings(journald.run, make_ctx(root.system()))
    assert f.risk == REVIEW and f.bytes > 100000
    assert f.fix[0] == "sudo journalctl --vacuum-size=200M"


def test_logs_rotated_and_runaway(root, monkeypatch):
    monkeypatch.setattr(logs, "MIN_ROTATED", 1000)
    monkeypatch.setattr(logs, "BIG_ACTIVE", 100000)
    for name in ["syslog.1", "syslog.2.gz", "nginx/access.log-20261001.gz", "auth.log.old"]:
        root.write("/var/log/" + name, size=20000)
    root.write("/var/log/app/huge.log", size=150000)
    root.write("/var/log/app/small.log", size=10)
    root.write("/var/log/journal/x/system.journal", size=150000)  # left to the journald check
    found = findings(logs.run, make_ctx(root.system()))
    rotated = [f for f in found if f.key == "rotated"]
    big = [f for f in found if f.key != "rotated"]
    assert rotated[0].title.startswith("4 rotated")
    assert [f.key for f in big] == ["/var/log/app/huge.log"]
    assert big[0].fix[0] == "sudo truncate -s 0 /var/log/app/huge.log"


def test_logs_rotated_pattern():
    match = logs.ROTATED_RE.search
    for name in ["syslog.1", "syslog.2.gz", "x.log-20260101", "x.log-20260101.gz", "y.zst", "z.old"]:
        assert match(name), name
    for name in ["syslog", "app.log", "dpkg.log", "lastlog", "wtmp"]:
        assert not match(name), name


def test_packages(root, monkeypatch):
    monkeypatch.setattr(packages, "MIN_BYTES", 20000)
    root.write("/var/cache/apt/archives/a.deb", size=50000)
    root.write("/var/cache/dnf/tiny", size=10)  # one 4 KB block, under the floor
    found = findings(packages.run, make_ctx(root.system()))
    assert [(f.key, f.risk, f.fix) for f in found] == [("apt", SAFE, ["sudo apt-get clean"])]


def test_kernels_keeps_running_and_newest(root, monkeypatch):
    monkeypatch.setattr(kernels, "MIN_BYTES", 1000)
    for v in ["5.15.0-91-generic", "6.8.0-31-generic", "6.8.0-40-generic", "6.8.0-45-generic"]:
        root.write("/lib/modules/%s/kernel/x.ko" % v, size=5000)
        root.write("/boot/vmlinuz-%s" % v, size=2000)
    root.kernel("6.8.0-40-generic")  # running an older kernel than the newest installed
    f, = findings(kernels.run, make_ctx(root.system()))
    assert f.evidence == ["5.15.0-91-generic", "6.8.0-31-generic"]
    assert f.fix[0] == "sudo apt autoremove --purge"
    assert f.risk == REVIEW


def test_kernel_version_sorting():
    vs = ["6.8.0-9-generic", "6.8.0-10-generic", "5.15.0-100-generic"]
    assert max(vs, key=kernels.version_key) == "6.8.0-10-generic"


def test_snaps(root, monkeypatch):
    monkeypatch.setattr(snaps, "MIN_BYTES", 1000)
    root.write("/var/lib/snapd/snaps/core22_1564.snap", size=5000)
    root.write("/var/lib/snapd/snaps/core22_1621.snap", size=5000)
    root.commands[("snap", "list", "--all")] = (
        "Name    Version   Rev   Tracking       Publisher   Notes\n"
        "core22  20240809  1564  latest/stable  canonical✓  base,disabled\n"
        "core22  20241001  1621  latest/stable  canonical✓  base\n")
    f, = findings(snaps.run, make_ctx(root.system()))
    assert f.fix[0] == "sudo snap remove core22 --revision=1564"
    assert f.risk == SAFE


def test_crashes(root, monkeypatch):
    monkeypatch.setattr(crashes, "MIN_BYTES", 1000)
    root.write("/var/crash/_usr_bin_x.crash", size=5000)
    f, = findings(crashes.run, make_ctx(root.system()))
    assert f.key == "/var/crash"


def test_tmp_only_counts_old_files(root, monkeypatch):
    monkeypatch.setattr(tmpfiles, "MIN_BYTES", 1000)
    root.write("/tmp/old/build.tar", size=5000, age_days=30)
    root.write("/tmp/new.bin", size=50000)
    f, = findings(tmpfiles.run, make_ctx(root.system()))
    assert f.evidence[0].endswith("/tmp/old/build.tar")
    assert f.bytes < 50000


def test_torch_cache_counts_only_hub(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    root.write("/home/alice/.cache/torch/hub/checkpoints/model.pt", size=50000)
    root.write("/home/alice/.cache/torch/extensions/build.so", size=100000)
    ctx = make_ctx(root.system())
    found = [f for f in usercaches.run(ctx) if f.key == "PyTorch hub cache"]
    assert len(found) == 1
    assert found[0].bytes == ctx.size("/home/alice/.cache/torch/hub")
    assert found[0].fix == ["sudo -u alice -H sh -c 'rm -rf ~/.cache/torch/hub'"]


def test_torch_cache_ignores_large_non_hub_cache(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    root.write("/home/alice/.cache/torch/extensions/build.so", size=100000)
    found = list(usercaches.run(make_ctx(root.system())))
    assert not any(f.key == "PyTorch hub cache" for f in found)


def test_user_caches_grouped_across_users(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    root.write("/home/alice/.cache/pip/http/a", size=16000)
    root.write("/root/.cache/pip/http/b", size=12000)  # only over the floor together
    root.write("/home/alice/.m2/repository/x.jar", size=10)  # one 4 KB block, under the floor
    found = findings(usercaches.run, make_ctx(root.system()))
    assert [f.key for f in found] == ["pip cache"]
    assert found[0].fix == ["sudo -u alice -H sh -c 'pip cache purge'", "pip cache purge"]


def test_developer_caches_include_correct_cleanup_commands(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    cases = [
        (".cache/ccache", "ccache cache", 'CCACHE_DIR="$HOME/.cache/ccache" ccache -C', SAFE),
        (".ccache", "ccache legacy cache", 'CCACHE_DIR="$HOME/.ccache" ccache -C', SAFE),
        (".cache/sccache", "sccache cache", "rm -rf ~/.cache/sccache", SAFE),
        (".cache/ms-playwright", "Playwright browsers", "npx playwright uninstall --all", SAFE),
        (".cache/puppeteer", "Puppeteer browsers", "rm -rf ~/.cache/puppeteer", SAFE),
        (".cache/JetBrains", "JetBrains IDE caches",
         "du -sh ~/.cache/JetBrains/*  # remove only unused IDE versions", REVIEW),
    ]
    for path, _name, _cmd, _risk in cases:
        root.write("/home/alice/" + path + "/artifact", size=30000)

    found = {f.key: f for f in findings(usercaches.run, make_ctx(root.system()))}
    for _path, name, command, risk in cases:
        assert found[name].risk == risk
        assert found[name].fix == ["sudo -u alice -H sh -c '%s'" % command]
        assert found[name].bytes >= 30000


def test_developer_caches_are_grouped_across_users(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    root.write("/home/alice/.cache/sccache/artifact", size=16000)
    root.write("/root/.cache/sccache/artifact", size=12000)
    found = [f for f in findings(usercaches.run, make_ctx(root.system()))
             if f.key == "sccache cache"]
    assert len(found) == 1
    assert found[0].fix == [
        "sudo -u alice -H sh -c 'rm -rf ~/.cache/sccache'",
        "rm -rf ~/.cache/sccache",
    ]


def test_docker_system_df_and_container_logs(root, monkeypatch):
    monkeypatch.setattr(containers, "MIN_RECLAIM", 1000)
    monkeypatch.setattr(containers, "BIG_LOG", 1000)
    cid = "a" * 64
    root.write("/var/lib/docker/containers/%s/%s-json.log" % (cid, cid), size=20000)
    root.write("/var/lib/docker/containers/%s/config.v2.json" % cid, '{"Name": "/web"}')
    root.commands[("docker", "info", "--format", "{{.DockerRootDir}}")] = "/var/lib/docker\n"
    root.commands[("docker", "system", "df", "--format", "{{json .}}")] = (
        '{"Type":"Images","TotalCount":"5","Active":"2","Size":"3GB","Reclaimable":"2.5GB (83%)"}\n'
        '{"Type":"Build Cache","TotalCount":"10","Active":"0","Size":"1.2GB","Reclaimable":"1.2GB"}\n'
        '{"Type":"Local Volumes","TotalCount":"1","Active":"1","Size":"5MB","Reclaimable":"0B (0%)"}\n')
    found = {f.key: f for f in findings(containers.docker, make_ctx(root.system()))}
    assert found["images"].bytes == 2500000000 and found["images"].risk == REVIEW
    assert found["build-cache"].fix == ["docker builder prune -f"]
    assert "local-volumes" not in found
    assert found["log:web"].risk == CAUTION
    assert "docker inspect" in found["log:web"].fix[0]


def test_docker_without_access_leaves_a_note(root):
    root.mkdir("/var/lib/docker")
    ctx = make_ctx(root.system())
    assert findings(containers.docker, ctx) == []
    assert any("docker system df" in n for n in ctx.notes)


def test_inodes_and_reserved(root):
    system = root.system()
    ctx = make_ctx(system)
    fs = ctx.targets[0]
    fs.inodes, fs.inodes_free = 1000, 5
    fs.mountpoint = "/srv"
    fs.size, fs.used, fs.avail, fs.reserved = 1000, 950, 0, 50
    found = {f.check: f for f in findings(space.inodes, ctx) + findings(space.reserved, ctx)}
    assert found["inodes"].risk == INFO and found["inodes"].priority > 0
    assert found["reserved"].risk == CAUTION
    assert found["reserved"].fix == ["sudo tune2fs -m 1 /dev/sda1"]
    fs.mountpoint = "/"
    r, = findings(space.reserved, ctx)
    assert r.risk == INFO and r.fix == []


def test_active_log_fix_preserves_the_full_path(root, monkeypatch):
    monkeypatch.setattr(logs, "BIG_ACTIVE", 20000)
    paths = ["/var/log/my app/current.log", "/var/log/team's app/current.log",
             "/var/log/app[1].log"]
    for path in paths:
        root.write(path, size=50000)
    found = findings(logs.run, make_ctx(root.system()))
    assert {f.key for f in found} == set(paths)
    for f in found:
        assert shlex.split(f.fix[0]) == ["sudo", "truncate", "-s", "0", f.key]
        assert f.fix[0].endswith(shlex.quote(f.key))


def test_mysql_binary_logs_only(root, monkeypatch):
    monkeypatch.setattr(mysql, "MIN_BYTES", 20000)
    paths = ["/var/lib/mysql/binlog.000001", "/var/lib/mysql/mysql-bin.000002"]
    for path in paths:
        root.write(path, size=16000)
    for name in ["binlog.index", "binlog.1.bak", "binlog.000003x", "ibdata1", "relay.000001"]:
        root.write("/var/lib/mysql/" + name, size=50000)
    root.mkdir("/var/lib/mysql/binlog.000004")
    os.symlink(root.local(paths[0]), root.local("/var/lib/mysql/binlog.000005"))
    system = root.system()
    f, = findings(mysql.run, make_ctx(system))
    assert f.bytes == sum(system.lstat(path).st_blocks * 512 for path in paths)
    assert f.evidence == paths
    assert f.risk == REVIEW
    assert f.dev == system.lstat(paths[0]).st_dev
    assert 'PURGE BINARY LOGS' in f.fix[1]
    assert all("rm " not in line for line in f.fix)


def test_mysql_skips_missing_and_small_logs(root, monkeypatch):
    monkeypatch.setattr(mysql, "MIN_BYTES", 20000)
    assert findings(mysql.run, make_ctx(root.system())) == []
    root.write("/var/lib/mysqld/mysql-bin.000001", size=1000)
    assert findings(mysql.run, make_ctx(root.system())) == []


def test_mysql_reports_alternate_data_directory(root, monkeypatch):
    monkeypatch.setattr(mysql, "MIN_BYTES", 20000)
    root.write("/var/lib/mysqld/mariadb-bin.000001", size=50000)
    f, = findings(mysql.run, make_ctx(root.system()))
    assert f.key == "/var/lib/mysqld"


def test_mysql_respects_target_filesystem(root, monkeypatch):
    monkeypatch.setattr(mysql, "MIN_BYTES", 20000)
    root.write("/var/lib/mysql/binlog.000001", size=50000)
    root.mounts.append(("/var/lib/mysql", "ext4", "/dev/sdb1"))
    system = root.system()
    assert findings(mysql.run, make_ctx(system)) == []
    f, = findings(mysql.run, make_ctx(system, mountpoint="/var/lib/mysql"))
    assert f.dev == system.lstat("/var/lib/mysql").st_dev


def test_postgresql_finds_standard_cluster_layouts(root, monkeypatch):
    monkeypatch.setattr(postgresql, "MIN_BYTES", 20000)
    paths = ["/var/lib/postgresql/16/main/pg_wal", "/var/lib/pgsql/data/pg_wal",
             "/var/lib/pgsql/9.6/data/pg_xlog"]
    for path in paths:
        root.write(path + "/000000010000000000000001", size=50000)
    ctx = make_ctx(root.system())
    found = findings(postgresql.run, ctx)
    assert {f.key for f in found} == set(paths)
    assert all(f.risk == INFO and f.bytes == ctx.size(f.key) for f in found)
    assert all("Never delete WAL by hand" in f.detail for f in found)
    assert all("pg_replication_slots" in f.fix[0] for f in found)
    assert all("pg_stat_archiver" in f.fix[1] for f in found)


def test_postgresql_skips_missing_small_and_symlinked_wal(root, monkeypatch):
    monkeypatch.setattr(postgresql, "MIN_BYTES", 20000)
    assert findings(postgresql.run, make_ctx(root.system())) == []
    root.write("/var/lib/pgsql/data/pg_wal/segment", size=1000)
    root.mkdir("/var/lib/postgresql/16/main")
    root.write("/elsewhere/segment", size=50000)
    os.symlink(root.local("/elsewhere"), root.local("/var/lib/postgresql/16/main/pg_wal"))
    assert findings(postgresql.run, make_ctx(root.system())) == []


def test_postgresql_respects_separate_wal_filesystem(root, monkeypatch):
    monkeypatch.setattr(postgresql, "MIN_BYTES", 20000)
    path = "/var/lib/postgresql/16/main/pg_wal"
    root.write(path + "/segment", size=50000)
    root.mounts.append((path, "ext4", "/dev/sdb1"))
    system = root.system()
    assert findings(postgresql.run, make_ctx(system)) == []
    f, = findings(postgresql.run, make_ctx(system, mountpoint=path))
    assert f.dev == system.lstat(path).st_dev


def test_bazel_cache_grouped_with_review_guidance(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    root.write("/home/alice/.cache/bazel/output/artifact", size=16000)
    root.write("/root/.cache/bazel/output/artifact", size=12000)
    found = findings(usercaches.run, make_ctx(root.system()))
    assert [f.key for f in found] == ["Bazel cache"]
    assert found[0].risk == REVIEW
    assert len(found[0].evidence) == 2
    assert "bazel clean --expunge" in found[0].fix[0]
    assert "each workspace" in found[0].fix[0]


def test_bazel_cache_skips_missing_and_small_directories(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    assert findings(usercaches.run, make_ctx(root.system())) == []
    root.write("/home/alice/.cache/bazel/output/artifact", size=1000)
    assert findings(usercaches.run, make_ctx(root.system())) == []


def test_bazel_cache_respects_selected_filesystem(root, monkeypatch):
    monkeypatch.setattr(usercaches, "MIN_BYTES", 20000)
    path = "/home/alice/.cache/bazel"
    root.write(path + "/output/artifact", size=50000)
    root.mounts.append((path, "ext4", "/dev/sdb1"))
    system = root.system()
    assert findings(usercaches.run, make_ctx(system)) == []
    ctx = make_ctx(system, mountpoint=path)
    f, = findings(usercaches.run, ctx)
    assert f.key == "Bazel cache"
    assert f.dev == system.lstat(path).st_dev
    assert f.bytes == ctx.size(path)

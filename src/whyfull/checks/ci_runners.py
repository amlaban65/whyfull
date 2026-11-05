"""GitHub Actions and GitLab Runner work directories on Linux servers."""

import fnmatch
import os
import shlex
import stat

from whyfull.checks import check
from whyfull.model import REVIEW, Finding
from whyfull.units import human

MIN_BYTES = 2 * 10 ** 9


def _directory(ctx, path):
    info = ctx.system.lstat(path)
    return info is not None and stat.S_ISDIR(info.st_mode) and ctx.on_target(path)


def _github_installations(ctx):
    candidates = ["/opt/actions-runner", "/home/runner/actions-runner"]
    candidates.extend(os.path.join(home, "actions-runner") for _, home in ctx.system.users())
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if _directory(ctx, path) and ctx.system.exists(os.path.join(path, ".runner")):
            yield path


def _gitlab_homes(ctx):
    # gitlab-runner normally has a system UID, so system.users() excludes it.
    for line in (ctx.system.read_text("/etc/passwd") or "").splitlines():
        parts = line.split(":")
        if len(parts) >= 6 and parts[0] == "gitlab-runner" and parts[5].startswith("/"):
            yield parts[5]


@check("ci-runners", "CI runner work directories and caches")
def run(ctx):
    for install in _github_installations(ctx):
        work = os.path.join(install, "_work")
        if not _directory(ctx, work):
            continue
        total = ctx.size(work)
        if total < MIN_BYTES:
            continue
        tools = os.path.join(work, "_tool")
        tool_bytes = ctx.size(tools) if _directory(ctx, tools) else 0
        yield Finding(
            "ci-runners", work, "GitHub Actions self-hosted runner workspace",
            total, REVIEW, ctx.dev_of(work),
            detail=("Workspace size includes downloaded runner tools (%s). "
                    "Only clean after stopping the runner or confirming that no job is active. "
                    "Tools will be downloaded again if removed." % human(tool_bytes)),
            evidence=["%s  %s" % (human(total), work),
                      "%s  %s (included above)" % (human(tool_bytes), tools)],
            fix=[
                "# Stop the self-hosted runner or verify that it is idle first.",
                "# Keep _tool to avoid re-downloading tool versions:",
                "sudo find %s -mindepth 1 -maxdepth 1 ! -name _tool -exec rm -rf -- {} +"
                % shlex.quote(work),
            ],
        )

    seen = set()
    for home in _gitlab_homes(ctx):
        if home in seen:
            continue
        seen.add(home)
        for name in ("builds", "cache"):
            path = os.path.join(home, name)
            if not _directory(ctx, path):
                continue
            size = ctx.size(path)
            if size < MIN_BYTES:
                continue
            yield Finding(
                "ci-runners", path, "GitLab Runner %s" % name,
                size, REVIEW, ctx.dev_of(path),
                detail=("GitLab Runner shell executor %s may contain files from active jobs. "
                        "Stop or check that the runner is idle before cleaning." % name),
                evidence=["%s  %s" % (human(size), path)],
                fix=[
                    "# Stop GitLab Runner or verify no job is active first.",
                    "sudo find %s -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +"
                    % shlex.quote(path),
                ],
            )

    # GitLab's Docker executor can also leave its cache in named volumes.
    volumes = ctx.system.run(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if volumes is None:
        return
    for name in volumes.splitlines():
        name = name.strip()
        if not fnmatch.fnmatchcase(name, "runner-*-cache-*"):
            continue
        if ctx.budget.expired():
            break
        mountpoint = ctx.system.run([
            "docker", "volume", "inspect", "--format", "{{.Mountpoint}}", name,
        ])
        if not mountpoint:
            continue
        path = mountpoint.strip()
        if not path.startswith("/") or not _directory(ctx, path):
            continue
        size = ctx.size(path)
        if size < MIN_BYTES:
            continue
        yield Finding(
            "ci-runners", "docker:" + name, "GitLab Runner Docker cache volume",
            size, REVIEW, ctx.dev_of(path),
            detail=("Only remove unused cache volumes after checking the GitLab "
                    "Runner is idle and no job needs this volume."),
            evidence=["%s  %s" % (human(size), path)],
            fix=[
                "# Check GitLab Runner's clear-docker-cache script before bulk cleanup.",
                "# Inspect this volume and confirm it is unused before removal:",
                "docker volume inspect %s" % shlex.quote(name),
                "docker volume rm %s" % shlex.quote(name),
            ],
        )

"""Per-user caches that build tools and package managers keep forever."""

import os

from whyfull.checks import check
from whyfull.model import REVIEW, SAFE, Finding
from whyfull.units import human

MIN_BYTES = 200 * 10 ** 6

# (relative path, title, command run as the owning user, risk)
CACHES = [
    (".cache/pip", "pip cache", "pip cache purge", SAFE),
    (".cache/uv", "uv cache", "uv cache clean", SAFE),
    (".cache/pypoetry", "Poetry cache", "rm -rf ~/.cache/pypoetry/cache ~/.cache/pypoetry/artifacts", SAFE),
    (".npm/_cacache", "npm cache", "npm cache clean --force", SAFE),
    (".cache/yarn", "Yarn cache", "yarn cache clean", SAFE),
    (".local/share/pnpm/store", "pnpm store", "pnpm store prune", SAFE),
    (".cache/deno", "Deno cache", 'DENO_DIR="$HOME/.cache/deno" deno clean', SAFE),
    (".cache/go-build", "Go build cache", "go clean -cache", SAFE),
    (".cache/ccache", "ccache cache", 'CCACHE_DIR="$HOME/.cache/ccache" ccache -C', SAFE),
    (".ccache", "ccache legacy cache", 'CCACHE_DIR="$HOME/.ccache" ccache -C', SAFE),
    (".cache/sccache", "sccache cache", "rm -rf ~/.cache/sccache", SAFE),
    (".cache/ms-playwright", "Playwright browsers", "npx playwright uninstall --all", SAFE),
    (".cache/puppeteer", "Puppeteer browsers", "rm -rf ~/.cache/puppeteer", SAFE),
    (".cache/JetBrains", "JetBrains IDE caches",
     "du -sh ~/.cache/JetBrains/*  # remove only unused IDE versions", REVIEW),
    ("go/pkg/mod", "Go module cache", "go clean -modcache", SAFE),
    (".cargo/registry", "Cargo registry cache", "rm -rf ~/.cargo/registry/cache ~/.cargo/registry/src", SAFE),
    (".m2/repository", "Maven repository", "rm -rf ~/.m2/repository", SAFE),
    (".gradle/caches", "Gradle caches", "rm -rf ~/.gradle/caches", SAFE),
    (".cache/huggingface", "Hugging Face models and datasets",
     "huggingface-cli delete-cache  # interactive: pick what to remove", REVIEW),
    (".cache/torch/hub", "PyTorch hub cache", "rm -rf ~/.cache/torch/hub", REVIEW),
    (".conda/pkgs", "conda package cache", "conda clean --all -y", SAFE),
    ("miniconda3/pkgs", "conda package cache", "conda clean --all -y", SAFE),
    ("anaconda3/pkgs", "conda package cache", "conda clean --all -y", SAFE),
    (".local/share/Trash", "Trash", "rm -rf ~/.local/share/Trash/*", REVIEW),
]


@check("user-caches", "Build tool and package caches in home directories")
def run(ctx):
    groups = {}  # (title, dev) -> dict
    for user, home in ctx.system.users():
        for rel, title, cmd, risk in CACHES:
            path = os.path.join(home, rel)
            if not ctx.system.exists(path) or not ctx.on_target(path):
                continue
            size = ctx.size(path)
            if size == 0:
                continue
            g = groups.setdefault((title, ctx.dev_of(path)), {"bytes": 0, "users": [], "cmd": cmd, "risk": risk})
            g["bytes"] += size
            g["users"].append((size, user, path))

    for (title, dev), g in sorted(groups.items(), key=lambda kv: -kv[1]["bytes"]):
        if g["bytes"] < MIN_BYTES:
            continue
        g["users"].sort(reverse=True)
        fix = []
        for _size, user, _path in g["users"]:
            quoted = g["cmd"].replace("'", "'\\''")
            fix.append(g["cmd"] if user == "root" else "sudo -u %s -H sh -c '%s'" % (user, quoted))
        who = ", ".join(u for _, u, _ in g["users"][:3])
        yield Finding(
            "user-caches", title, "%s (%s)" % (title, who), g["bytes"], g["risk"], dev,
            detail="Downloaded or built artifacts kept for speed. Tools re-create them when needed.",
            fix=fix[:5],
            evidence=["%s  %s" % (human(s), p) for s, _, p in g["users"][:5]],
        )

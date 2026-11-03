"""Measuring disk usage, like du -x, with a time budget."""

import heapq
import os
import stat as statmod
import time


class Budget(object):
    """A deadline shared by several walks, so a huge disk can't hang the tool."""

    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds if seconds else None
        self.hit = False

    def expired(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            self.hit = True
            return True
        return False


class Usage(object):
    def __init__(self):
        self.bytes = 0
        self.files = 0
        self.complete = True
        self.denied = 0


def allocated(st):
    """Bytes actually allocated on disk (sparse files count only what they use)."""
    blocks = getattr(st, "st_blocks", None)
    if blocks is None:  # pragma: no cover - every Linux filesystem reports blocks
        return st.st_size
    return blocks * 512


def du(local_path, dev=None, budget=None, seen=None):
    """Total allocated bytes under local_path, staying on one filesystem.

    dev    -- only count files on this device (default: the device of local_path)
    seen   -- set of (dev, inode) already counted, so hard links count once
    """
    usage = Usage()
    seen = set() if seen is None else seen
    try:
        top = os.lstat(local_path)
    except OSError:
        return usage
    if dev is None:
        dev = top.st_dev
    if top.st_dev != dev:
        return usage
    if not statmod.S_ISDIR(top.st_mode):
        usage.bytes = allocated(top)
        usage.files = 1
        return usage

    stack = [local_path]
    while stack:
        if budget is not None and budget.expired():
            usage.complete = False
            break
        path = stack.pop()
        try:
            it = os.scandir(path)
        except PermissionError:
            usage.denied += 1
            continue
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_dev != dev:
                    continue
                if statmod.S_ISDIR(st.st_mode):
                    stack.append(entry.path)
                    continue
                if st.st_nlink > 1:
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                usage.bytes += allocated(st)
                usage.files += 1
    return usage


class Tree(object):
    """Result of scanning a whole filesystem."""

    def __init__(self):
        self.sizes = {}  # local dir path (depth <= max_depth) -> bytes, cumulative
        self.total = 0
        self.files = 0
        self.complete = True
        self.denied = 0
        self.crowded = []  # (entry count, local dir path), most entries first


def scan(local_root, dev, budget=None, max_depth=3, crowded=10, exclude=None):
    """Walk a filesystem from its mountpoint, recording directory sizes down to
    max_depth and the directories with the most entries (for inode trouble).
    exclude contains local paths to omit, including their entire subtrees.
    """
    tree = Tree()
    excluded = {os.path.normcase(os.path.abspath(p)) for p in (exclude or [])}
    prefixes = tuple(p.rstrip(os.sep) + os.sep for p in excluded)

    def is_excluded(path):
        if not excluded:
            return False
        path = os.path.normcase(os.path.abspath(path))
        return path in excluded or path.startswith(prefixes)

    seen = set()
    buckets = {}  # nearest recorded ancestor -> bytes directly attributed
    heap = []  # min-heap of (entries, path)
    # stack items: (path, depth, bucket path)
    stack = [(local_root, 0, local_root)]
    while stack:
        if budget is not None and budget.expired():
            tree.complete = False
            break
        path, depth, bucket = stack.pop()
        if is_excluded(path):
            continue
        try:
            it = os.scandir(path)
        except PermissionError:
            tree.denied += 1
            continue
        except OSError:
            continue
        entries = 0
        direct = 0
        with it:
            for entry in it:
                if is_excluded(entry.path):
                    continue
                entries += 1
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_dev != dev:
                    continue
                if statmod.S_ISDIR(st.st_mode):
                    child_depth = depth + 1
                    child_bucket = entry.path if child_depth <= max_depth else bucket
                    stack.append((entry.path, child_depth, child_bucket))
                    continue
                if st.st_nlink > 1:
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                direct += allocated(st)
                tree.files += 1
        buckets[bucket] = buckets.get(bucket, 0) + direct
        tree.total += direct
        if crowded:
            if len(heap) < crowded:
                heapq.heappush(heap, (entries, path))
            elif entries > heap[0][0]:
                heapq.heapreplace(heap, (entries, path))

    # Roll each bucket up into its recorded ancestors.
    root = local_root.rstrip("/") or "/"
    for path, nbytes in buckets.items():
        p = path
        while True:
            tree.sizes[p] = tree.sizes.get(p, 0) + nbytes
            if p == root or len(p) <= len(root):
                break
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    tree.crowded = sorted(heap, reverse=True)
    return tree

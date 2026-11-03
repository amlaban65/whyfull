"""Unused images in containerd or CRI-O, measured through the CRI API."""

import json

from whyfull.checks import check
from whyfull.model import REVIEW, Finding

MIN_BYTES = 200 * 10 ** 6
ROOTS = ("/var/lib/containerd", "/var/lib/containers/storage")


def _image_id(value):
    return value[len("sha256:"):] if value.startswith("sha256:") else value


@check("cri", "Unused Kubernetes container images")
def run(ctx):
    if not ctx.system.has("crictl"):
        return
    roots = [p for p in ROOTS if ctx.system.exists(p)]
    if not roots or not any(ctx.on_target(p) for p in roots):
        return
    devices = set(ctx.dev_of(p) for p in roots)
    if len(devices) != 1:
        ctx.note("CRI storage spans multiple filesystems; unused image bytes cannot be attributed safely.")
        return
    dev = devices.pop()
    try:
        images = json.loads(ctx.system.run(["crictl", "images", "-o", "json"]) or "null")
        containers = json.loads(ctx.system.run(["crictl", "ps", "-a", "-o", "json"]) or "null")
        if not isinstance(images, dict) or not isinstance(containers, dict):
            raise ValueError("missing output")
        images, containers = images["images"], containers["containers"]
        if not isinstance(images, list) or not isinstance(containers, list):
            raise ValueError("invalid lists")
        used = set()
        for container in containers:
            ref = container.get("imageRef") or container.get("image", {}).get("image")
            if not isinstance(ref, str) or not ref:
                raise ValueError("container has no image reference")
            used.add(_image_id(ref))
        unused = {}
        for image in images:
            if image.get("pinned"):
                continue  # The runtime retains pinned images during garbage collection.
            image_id = image["id"]
            size = image["size"]
            if not isinstance(image_id, str) or not image_id:
                raise ValueError("invalid image id")
            # CRI protobuf JSON represents uint64 sizes as decimal strings.
            if isinstance(size, bool) or not isinstance(size, (str, int)):
                raise ValueError("invalid image size")
            size = int(size)
            if size < 0:
                raise ValueError("negative image size")
            aliases = [image_id] + (image.get("repoTags") or []) + (image.get("repoDigests") or [])
            if any(_image_id(alias) in used for alias in aliases):
                continue
            unused[_image_id(image_id)] = size
    except (ValueError, TypeError, KeyError, AttributeError):
        ctx.note("CRI image/container inventory was unavailable or invalid; unused image bytes were not estimated.")
        return
    size = sum(unused.values())
    if size < MIN_BYTES:
        return
    yield Finding(
        "cri", "unused-images", "%d Kubernetes images not used by any container" % len(unused),
        size, REVIEW, dev,
        detail=("Includes images referenced by neither running nor stopped containers. "
                "Image layers may be shared, so the image sizes can overestimate space actually freed."),
        fix=["sudo crictl rmi --prune"],
        evidence=["CRI-reported unused image size: %d bytes; shared layers are not deduplicated" % size],
    )

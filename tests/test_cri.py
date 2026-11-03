import json

import pytest

from conftest import make_ctx
from whyfull.checks import cri
from whyfull.model import REVIEW


def inventory(root, images, containers):
    root.mkdir("/var/lib/containerd")
    root.commands[("crictl", "images", "-o", "json")] = json.dumps({"images": images})
    root.commands[("crictl", "ps", "-a", "-o", "json")] = json.dumps({"containers": containers})


def test_unused_images_exclude_all_container_references(root, monkeypatch):
    monkeypatch.setattr(cri, "MIN_BYTES", 20000)
    inventory(root, [
        {"id": "sha256:used", "size": "90000"},
        {"id": "sha256:tagged", "repoTags": ["example/image:v1"], "size": 80000},
        {"id": "sha256:unused", "size": "50000"},
        {"id": "sha256:unused", "size": "50000"},
    ], [{"imageRef": "used"}, {"image": {"image": "example/image:v1"}}])
    finding, = list(cri.run(make_ctx(root.system())))
    assert finding.bytes == 50000
    assert finding.risk == REVIEW
    assert finding.fix == ["sudo crictl rmi --prune"]


@pytest.mark.parametrize("bad", [None, "not-json", '{"containers": null}'])
def test_unavailable_container_inventory_does_not_claim_reclaimable_bytes(root, monkeypatch, bad):
    monkeypatch.setattr(cri, "MIN_BYTES", 20000)
    inventory(root, [{"id": "unused", "size": 50000}], [])
    root.commands[("crictl", "ps", "-a", "-o", "json")] = bad
    ctx = make_ctx(root.system())
    assert list(cri.run(ctx)) == []
    assert ctx.notes


def test_missing_container_reference_does_not_treat_all_images_as_unused(root):
    inventory(root, [{"id": "unused", "size": 500000000}], [{}])
    assert list(cri.run(make_ctx(root.system()))) == []


def test_storage_outside_target_is_not_reported(root):
    inventory(root, [{"id": "unused", "size": 500000000}], [])
    root.mounts.append(("/var/lib/containerd", "ext4", "/dev/sdb1"))
    assert list(cri.run(make_ctx(root.system()))) == []


def test_missing_tool_and_small_inventory_are_silent(root):
    root.mkdir("/var/lib/containerd")
    assert list(cri.run(make_ctx(root.system()))) == []
    inventory(root, [{"id": "unused", "size": 1}], [])
    assert list(cri.run(make_ctx(root.system()))) == []


def test_pinned_images_are_not_reported_as_reclaimable(root, monkeypatch):
    monkeypatch.setattr(cri, "MIN_BYTES", 20000)
    inventory(root, [{"id": "pinned", "size": 50000, "pinned": True}], [])
    assert list(cri.run(make_ctx(root.system()))) == []


def test_ambiguous_storage_devices_do_not_misattribute_image_bytes(root):
    inventory(root, [{"id": "unused", "size": 500000000}], [])
    root.mkdir("/var/lib/containers/storage")
    root.mounts.append(("/var/lib/containers/storage", "ext4", "/dev/sdb1"))
    assert list(cri.run(make_ctx(root.system()))) == []

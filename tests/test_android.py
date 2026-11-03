import os

from conftest import make_ctx
from whyfull.checks import android
from whyfull.model import REVIEW


def test_avd_and_system_image_are_measured_without_commands(root, monkeypatch):
    monkeypatch.setattr(android, "MIN_BYTES", 20000)
    root.write("/home/alice/.android/avd/Pixel.avd/userdata.img", size=50000)
    root.write("/home/alice/Android/Sdk/system-images/android-34/google_apis/x86_64/system.img", size=60000)
    findings = list(android.run(make_ctx(root.system())))
    assert len(findings) == 2
    assert all(f.risk == REVIEW and f.bytes >= 50000 for f in findings)
    assert "delete avd -n Pixel" in findings[0].fix[1]
    assert "system-images;android-34;google_apis;x86_64" in findings[1].fix[1]
    assert "not necessarily unused" in findings[1].detail
    assert root.commands == {}


def test_small_or_non_avd_directories_are_ignored(root, monkeypatch):
    monkeypatch.setattr(android, "MIN_BYTES", 20000)
    root.write("/home/alice/.android/avd/small.avd/userdata.img", size=100)
    root.write("/home/alice/.android/avd/other/userdata.img", size=50000)
    assert list(android.run(make_ctx(root.system()))) == []


def test_images_on_other_filesystems_are_ignored(root, monkeypatch):
    monkeypatch.setattr(android, "MIN_BYTES", 20000)
    path = "/home/alice/.android/avd/Pixel.avd"
    root.write(path + "/userdata.img", size=50000)
    root.mounts.append((path, "ext4", "/dev/sdb1"))
    assert list(android.run(make_ctx(root.system()))) == []


def test_all_users_and_quoted_avd_names(root, monkeypatch):
    monkeypatch.setattr(android, "MIN_BYTES", 20000)
    root.write("/root/.android/avd/Root.avd/data", size=50000)
    root.write("/home/alice/.android/avd/Pixel tablet.avd/data", size=50000)
    findings = list(android.run(make_ctx(root.system())))
    assert len(findings) == 2
    assert findings[0].fix[0] == "avdmanager list avd"
    assert findings[1].fix[0].startswith("sudo -u alice -H sh -c ")
    assert "Pixel tablet" in findings[1].fix[1]


def test_symlinks_are_not_followed(root, monkeypatch):
    monkeypatch.setattr(android, "MIN_BYTES", 20000)
    target = root.write("/data/real/data", size=50000)
    root.mkdir("/home/alice/.android/avd")
    os.symlink(os.path.dirname(target), root.local("/home/alice/.android/avd/link.avd"))
    assert list(android.run(make_ctx(root.system()))) == []


def test_missing_android_installations_are_silent(root):
    assert list(android.run(make_ctx(root.system()))) == []

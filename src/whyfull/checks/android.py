"""Android emulator data and installed SDK system images."""

import posixpath
import shlex
import stat

from whyfull.checks import check
from whyfull.model import REVIEW, Finding
from whyfull.units import human

MIN_BYTES = 10 ** 9


def _directories(ctx, parent):
    for name in ctx.system.listdir(parent):
        path = posixpath.join(parent, name)
        info = ctx.system.lstat(path)
        if info is not None and stat.S_ISDIR(info.st_mode) and ctx.on_target(path):
            yield name, path


def _as_user(user, command):
    return command if user == "root" else "sudo -u %s -H sh -c %s" % (shlex.quote(user), shlex.quote(command))


@check("android", "Android emulator data and SDK system images")
def run(ctx):
    for user, home in ctx.system.users():
        avds = posixpath.join(home, ".android/avd")
        for name, path in _directories(ctx, avds):
            if not name.endswith(".avd"):
                continue
            size = ctx.size(path)
            if size < MIN_BYTES:
                continue
            yield Finding(
                "android", path, "Android emulator %s (%s)" % (name[:-4], user), size, REVIEW, ctx.dev_of(path),
                detail="Contains the emulator's apps and user data. Review the AVD before deleting it.",
                fix=[_as_user(user, "avdmanager list avd"),
                     _as_user(user, "avdmanager delete avd -n %s" % shlex.quote(name[:-4]))],
                evidence=["%s  %s" % (human(size), path)],
            )
        sdk = posixpath.join(home, "Android/Sdk")
        images = posixpath.join(sdk, "system-images")
        for api, api_path in _directories(ctx, images):
            for vendor, vendor_path in _directories(ctx, api_path):
                for arch, path in _directories(ctx, vendor_path):
                    size = ctx.size(path)
                    if size < MIN_BYTES:
                        continue
                    package = "system-images;%s;%s;%s" % (api, vendor, arch)
                    manager = "sdkmanager --sdk_root=%s" % shlex.quote(sdk)
                    yield Finding(
                        "android", path, "Android SDK image %s (%s)" % (package, user),
                        size, REVIEW, ctx.dev_of(path),
                        detail=("An installed system image, not necessarily unused. "
                                "Check whether an AVD still needs it before uninstalling."),
                        fix=[_as_user(user, manager + " --list_installed"),
                             _as_user(user, manager + " --uninstall " + shlex.quote(package))],
                        evidence=["%s  %s" % (human(size), path)],
                    )

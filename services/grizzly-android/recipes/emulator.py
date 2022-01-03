#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations
from __future__ import print_function
import argparse
import logging
import os
import platform
import shutil
import stat
import sys
import telnetlib
import tempfile
import time
import xml.etree.ElementTree
import zipfile
import requests
from six.moves.urllib.parse import urlparse

if sys.version_info.major == 2:
    import subprocess32 as subprocess  # pylint: disable=import-error
else:
    import subprocess
if platform.system() == "Linux":
    import xvfbwrapper


REPO_URL = "https://dl.google.com/android/repository/repository2-1.xml"
IMAGES_URL = "https://dl.google.com/android/repository/sys-img/android/sys-img2-1.xml"

HOME = os.path.expanduser("~")

LOG = logging.getLogger("emulator_install")


def si(number: float) -> str:
    suffixes = ["", "k", "M", "G", "T"]
    while number > 1024:
        number /= 1024.0
        suffixes.pop(0)
    return "%0.2f%s" % (number, suffixes.pop(0))


def makedirs(*dirs) -> str:
    while dirs:
        if not os.path.isdir(dirs[0]):
            os.mkdir(dirs[0])
        if len(dirs) == 1:
            return dirs[0]
        dirs = [os.path.join(dirs[0], dirs[1])] + list(dirs[2:])
    return ""


class AndroidSDKRepo(object):
    def __init__(self, url: str) -> None:
        parts = urlparse(url)
        self.url_base = (
            parts.scheme + "://" + parts.netloc + os.path.dirname(parts.path)
        )
        xml_string = requests.get(url).content
        LOG.info("Downloaded manifest: %s (%sB)", url, si(len(xml_string)))
        self.root = xml.etree.ElementTree.fromstring(xml_string)

    @staticmethod
    def read_revision(element: xml.etree.ElementTree.Element) -> tuple[int, int, int]:
        rev = element.find("revision")
        major = rev.find("major")
        major = int(major.text) if major is not None else None
        minor = rev.find("minor")
        minor = int(minor.text) if minor is not None else None
        micro = rev.find("micro")
        micro = int(micro.text) if micro is not None else None
        return (major, minor, micro)

    def get_file(
        self,
        package_path: str,
        out_path: str = ".",
        host: str = "linux",
        extract_package_path: bool = True,
    ) -> None:
        package = self.root.find(
            ".//remotePackage[@path='%s']/channelRef[@ref='channel-0']/.."
            % (package_path,)
        )
        if host is None:
            url = package.find("./archives/archive/complete/url")
        else:
            url = package.find(
                "./archives/archive/[host-os='%s']/complete/url" % (host,)
            )

        # figure out where to extract package to
        path_parts = package_path.split(";")
        intermediates = path_parts[:-1]
        manifest_path = os.path.join(out_path, *path_parts)
        manifest_path = os.path.join(manifest_path, "package.xml")
        if not extract_package_path:
            makedirs(out_path, *path_parts)
            # out_path doesn't change
        elif intermediates:
            makedirs(out_path, *intermediates)
            out_path = os.path.join(out_path, *intermediates)

        # check for an existing manifest
        if os.path.isfile(manifest_path):
            # compare the remote version with local
            remote_rev = self.read_revision(package)
            local_rev = self.read_revision(
                xml.etree.ElementTree.parse(manifest_path).find("localPackage")
            )
            if remote_rev <= local_rev:
                fmt_rev = ".".join(
                    "" if ver is None else ("%d" % (ver,)) for ver in local_rev
                ).strip(".")
                LOG.info(
                    "Installed %s revision %s is sufficiently new",
                    package_path,
                    fmt_rev,
                )
                return None

        tmp_fp, ziptmp = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fp)
        try:
            downloaded = 0
            with open(ziptmp, "wb") as zipf:
                response = requests.get(self.url_base + "/" + url.text, stream=True)
                total_size = int(response.headers["Content-Length"])
                start_time = report_time = time.time()
                LOG.info(
                    "Downloading package: %s (%sB total)", url.text, si(total_size)
                )
                for chunk in response.iter_content(1024 * 1024):
                    zipf.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if (now - report_time) > 30 and downloaded != total_size:
                        LOG.info(
                            ".. still downloading (%0.1f%%, %sB/s)",
                            100.0 * downloaded / total_size,
                            si(float(downloaded) / (now - start_time)),
                        )
                        report_time = now
            assert downloaded == total_size
            LOG.info(
                ".. downloaded (%sB/s)",
                si(float(downloaded) / (time.time() - start_time)),
            )
            with zipfile.ZipFile(ziptmp) as zipf:
                for info in zipf.infolist():
                    zipf.extract(info, out_path)
                    perm = info.external_attr >> 16
                    perm |= (
                        stat.S_IREAD
                    )  # make sure we're not accidentally setting this to 0
                    os.chmod(os.path.join(out_path, info.filename), perm)
        finally:
            os.unlink(ziptmp)

        # write manifest
        xml.etree.ElementTree.register_namespace(
            "common", "http://schemas.android.com/repository/android/common/01"
        )
        xml.etree.ElementTree.register_namespace(
            "generic", "http://schemas.android.com/repository/android/generic/01"
        )
        xml.etree.ElementTree.register_namespace(
            "sys-img", "http://schemas.android.com/sdk/android/repo/sys-img2/01"
        )
        xml.etree.ElementTree.register_namespace(
            "xsi", "http://www.w3.org/2001/XMLSchema-instance"
        )
        manifest = xml.etree.ElementTree.Element(
            "{http://schemas.android.com/repository/android/common/01}repository"
        )
        license = package.find("uses-license")
        manifest.append(self.root.find("./license[@id='%s']" % (license.get("ref"),)))
        local_package = xml.etree.ElementTree.SubElement(manifest, "localPackage")
        local_package.set("path", package_path)
        local_package.set("obsolete", "false")
        local_package.append(package.find("type-details"))
        local_package.append(package.find("revision"))
        local_package.append(package.find("display-name"))
        local_package.append(license)
        deps = package.find("dependencies")
        if deps is not None:
            local_package.append(deps)
        manifest_bytes = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + xml.etree.ElementTree.tostring(manifest, encoding="UTF-8")
        )
        # etree doesn't support xmlns in attribute values, so insert them manually
        if b"xmlns:generic=" not in manifest_bytes and b'"generic:' in manifest_bytes:
            manifest_bytes = manifest_bytes.replace(
                b"<common:repository ",
                b'<common:repository xmlns:generic="http://schemas.android.com/repository/android/generic/01" ',
            )
        if b"xmlns:sys-img=" not in manifest_bytes and b'"sys-img:' in manifest_bytes:
            manifest_bytes = manifest_bytes.replace(
                b"<common:repository ",
                b'<common:repository xmlns:sys-img="http://schemas.android.com/sdk/android/repo/sys-img2/01" ',
            )
        with open(manifest_path, "wb") as manifest_fp:
            manifest_fp.write(manifest_bytes)


class AndroidHelper(object):
    def __init__(
        self,
        android_port: int = 5554,
        avd_name=None,
        no_window: bool = False,
        sdcard_size: int = 500,
        use_snapshot: bool = False,
        writable: bool = False,
    ) -> None:
        self.android_port = android_port
        self.avd_name = avd_name
        self.no_window = no_window
        self.sdcard_size = sdcard_size
        self.use_snapshot = use_snapshot
        self.writable = writable

    def install(self) -> None:
        # create folder structure
        android = makedirs(HOME, "Android")
        avd_home = makedirs(HOME, ".android")
        makedirs(avd_home, "avd")
        sdk = makedirs(android, "Sdk")
        sdk_repo = AndroidSDKRepo(REPO_URL)
        img_repo = AndroidSDKRepo(IMAGES_URL)

        # get latest emulator for linux
        sdk_repo.get_file("emulator", sdk)

        # get latest Google APIs system image
        img_repo.get_file("system-images;android-29;default;x86_64", sdk, host=None)

        # get latest platform-tools for linux
        sdk_repo.get_file("platform-tools", sdk)

        # required for: aapt
        sdk_repo.get_file("build-tools;28.0.3", sdk, extract_package_path=False)

        # this is a hack and without it for some reason the following error can happen:
        # PANIC: Cannot find AVD system path. Please define ANDROID_SDK_ROOT
        makedirs(sdk, "platforms")

    def avd(self) -> None:
        # create folder structure
        android = makedirs(HOME, "Android")
        avd_home = makedirs(HOME, ".android")
        avd_path = makedirs(avd_home, "avd")
        sdk = os.path.join(android, "Sdk")
        api_gapi = os.path.join(sdk, "system-images", "android-29", "default")

        # create an avd
        avd_ini = os.path.join(avd_path, self.avd_name + ".ini")
        assert not os.path.isfile(avd_ini), "File exists %r" % avd_ini
        avd_dir = os.path.join(avd_path, self.avd_name + ".avd")
        os.mkdir(avd_dir)

        with open(avd_ini, "w") as fp:
            print("avd.ini.encoding=UTF-8", file=fp)
            print("path=" + avd_dir, file=fp)
            print("path.rel=avd/" + self.avd_name + ".avd", file=fp)
            print("target=android-28", file=fp)

        avd_cfg = os.path.join(avd_dir, "config.ini")
        assert not os.path.isfile(avd_cfg), "File exists %r" % avd_cfg
        with open(avd_cfg, "w") as fp:
            print("AvdId=" + self.avd_name, file=fp)
            print("PlayStore.enabled=false", file=fp)
            print("abi.type=x86_64", file=fp)
            print("avd.ini.displayname=" + self.avd_name, file=fp)
            print("avd.ini.encoding=UTF-8", file=fp)
            print("disk.dataPartition.size=5000M", file=fp)
            print("fastboot.forceColdBoot=no", file=fp)
            print("hw.accelerometer=yes", file=fp)
            print("hw.arc=false", file=fp)
            print("hw.audioInput=yes", file=fp)
            print("hw.battery=yes", file=fp)
            print("hw.camera.back=emulated", file=fp)
            print("hw.camera.front=emulated", file=fp)
            print("hw.cpu.arch=x86_64", file=fp)
            print("hw.cpu.ncore=4", file=fp)
            print("hw.dPad=no", file=fp)
            print("hw.device.hash2=MD5:524882cfa9f421413193056700a29392", file=fp)
            print("hw.device.manufacturer=Google", file=fp)
            print("hw.device.name=pixel", file=fp)
            print("hw.gps=yes", file=fp)
            print("hw.gpu.enabled=yes", file=fp)
            print("hw.gpu.mode=auto", file=fp)
            print("hw.initialOrientation=Portrait", file=fp)
            print("hw.keyboard=yes", file=fp)
            print("hw.lcd.density=480", file=fp)
            print("hw.lcd.height=1920", file=fp)
            print("hw.lcd.width=1080", file=fp)
            print("hw.mainKeys=no", file=fp)
            print("hw.ramSize=6144", file=fp)
            print("hw.sdCard=yes", file=fp)
            print("hw.sensors.orientation=yes", file=fp)
            print("hw.sensors.proximity=yes", file=fp)
            print("hw.trackBall=no", file=fp)
            print(
                "image.sysdir.1=system-images/android-28/google_apis/x86_64/", file=fp
            )
            print("runtime.network.latency=none", file=fp)
            print("runtime.network.speed=full", file=fp)
            print("sdcard.size=%dM" % (self.sdcard_size,), file=fp)
            print("showDeviceFrame=no", file=fp)
            print("skin.dynamic=yes", file=fp)
            print("skin.name=1080x1920", file=fp)
            print("skin.path=_no_skin", file=fp)
            print("skin.path.backup=_no_skin", file=fp)
            print("tag.display=Google APIs", file=fp)
            print("tag.id=google_apis", file=fp)
            print("vm.heapSize=256", file=fp)

        shutil.copy(os.path.join(api_gapi, "x86_64", "userdata.img"), avd_dir)

        sdcard = os.path.join(avd_dir, "sdcard.img")
        mksd = os.path.join(sdk, "emulator", "mksdcard")
        assert os.path.isfile(mksd), "Missing %s" % mksd
        subprocess.check_output([mksd, "%dM" % (self.sdcard_size,), sdcard])
        shutil.copy(sdcard, sdcard + ".firstboot")

    def emulator_run(self, use_snapshot: str, quiet: bool = True):
        # create folder structure
        android = makedirs(HOME, "Android")
        avd_home = makedirs(HOME, ".android")
        sdk = makedirs(android, "Sdk")
        avd_path = makedirs(avd_home, "avd")
        avd_dir = os.path.join(avd_path, self.avd_name + ".avd")
        emulator_bin = os.path.join(sdk, "emulator", "emulator")

        args = ["-selinux", "permissive"]

        if self.no_window:
            args.append("-no-window")

        if use_snapshot == "never":
            args.append("-no-snapshot")

        elif use_snapshot == "save":
            args.append("-no-snapshot-load")

        elif use_snapshot == "load":
            args.append("-no-snapshot-save")

            # replace sdcard with firstboot version if exists
            sdcard = os.path.join(avd_dir, "sdcard.img")
            if os.path.isfile(sdcard + ".firstboot"):
                if os.path.isfile(sdcard):
                    os.unlink(sdcard)
                shutil.copy(sdcard + ".firstboot", sdcard)

        if self.writable:
            args.append("-writable-system")

        args.extend(("-port", "%d" % (self.android_port,)))
        args.append("@" + self.avd_name)

        output = None
        if quiet:
            output = subprocess.DEVNULL

        result = subprocess.Popen([emulator_bin] + args, stderr=output, stdout=output)
        try:
            time.sleep(5)
        except Exception:
            if result.poll() is None:
                result.terminate()
            raise
        assert result.poll() is None, "Failed to launch emulator"

        return result

    def firstboot(self) -> None:
        # create folder structure
        android = makedirs(HOME, "Android")
        sdk = makedirs(android, "Sdk")
        avd_home = makedirs(HOME, ".android")
        avd_path = makedirs(avd_home, "avd")
        avd_dir = os.path.join(avd_path, self.avd_name + ".avd")
        sdcard = os.path.join(avd_dir, "sdcard.img")
        emulator_bin = os.path.join(sdk, "emulator", "emulator")

        # below does not work in docker build because it requires --privileged to launch an x86 emulator,
        # since kvm is required.
        LOG.info("Initial boot to save snapshot")

        proc = self.emulator_run("never")
        try:
            self.wait_for_boot_completed()
        except Exception:
            if proc.poll() is None:
                proc.terminate()
            raise

        proc.terminate()
        proc.wait()
        if os.path.isfile(sdcard + ".firstboot"):
            os.unlink(sdcard + ".firstboot")
        shutil.copy(sdcard, sdcard + ".firstboot")

        LOG.info("All done. Try running: `%s @%s`", emulator_bin, self.avd_name)

    def kill(self) -> None:
        ctl = telnetlib.Telnet("localhost", self.android_port)

        lines = ctl.read_until("OK\r\n", 10).rstrip().splitlines()
        try:
            auth_token_idx = lines.index(
                "Android Console: you can find your <auth_token> in "
            )
        except IndexError:
            pass
        else:
            auth_token_path = lines[auth_token_idx + 1].strip("'")
            with open(auth_token_path) as auth_token_fp:
                auth_token = auth_token_fp.read()
            ctl.write("auth %s\n" % (auth_token,))
            ctl.read_until("OK\r\n", 10)

        ctl.write("kill\n")
        ctl.close()

    def wait_for_boot_completed(self) -> None:
        # create folder structure
        android = makedirs(HOME, "Android")
        sdk = makedirs(android, "Sdk")
        platform_tools = makedirs(sdk, "platform-tools")

        subprocess.check_output(
            [
                os.path.join(platform_tools, "adb"),
                "wait-for-device",
                "shell",
                "while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done",
            ],
            timeout=60,
            env={"ANDROID_SERIAL": "emulator-%d" % (self.android_port,)},
        )
        time.sleep(5)

    def run(self) -> None:
        proc = self.emulator_run(self.use_snapshot, quiet=False)
        try:
            exit_code = proc.wait()
        except Exception:
            if proc.poll() is None:
                proc.terminate()
            raise
        assert exit_code == 0, "emulator returned %d" % (exit_code,)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    aparse = argparse.ArgumentParser()
    aparse.add_argument(
        "actions",
        nargs="*",
        choices=[
            "avd",
            "install",
            "firstboot",
            "kill",
            "run",
            "wait-for-boot-completed",
        ],
    )
    aparse.add_argument(
        "--android-port",
        default=5554,
        type=int,
        help="Port to run emulator on (default: 5554)",
    )
    aparse.add_argument(
        "--avd-name",
        default="x86_64",
        help="Name of AVD to create/use (default: x86_64)",
    )
    aparse.add_argument(
        "--no-window", action="store_true", help="Pass -no-window to emulator"
    )
    aparse.add_argument(
        "--sdcard", default=500, type=int, help="SD card size in MB (default: 500)"
    )
    aparse.add_argument(
        "--snapshot",
        default="never",
        choices=["never", "always", "save", "load"],
        help="Use snapshots for fast reset (default: never)",
    )
    aparse.add_argument(
        "--writable", action="store_true", help="Allow remount /system (default: False)"
    )
    aparse.add_argument("--xvfb", action="store_true", help="Run emulator under XVFB")
    args = aparse.parse_args()

    if args.xvfb and {"firstboot", "run"} & set(args.actions):
        xvfb = xvfbwrapper.Xvfb(width=1280, height=1024)
    else:
        xvfb = None

    try:
        if xvfb is not None:
            xvfb.start()

        ah = AndroidHelper(
            args.android_port,
            args.avd_name,
            args.no_window,
            args.sdcard,
            args.snapshot,
            args.writable,
        )
        for action in args.actions:
            getattr(ah, action.replace("-", "_"))()
    finally:
        if xvfb is not None:
            xvfb.stop()


if __name__ == "__main__":
    main()

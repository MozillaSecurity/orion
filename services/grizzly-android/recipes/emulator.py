#!/usr/bin/env python
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
IMAGES_URL = "https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-1.xml"

HOME = os.path.expanduser("~")

LOG = logging.getLogger("emulator_install")


def si(number):
    suffixes = ["", "k", "M", "G", "T"]
    while number > 1024:
        number /= 1024.0
        suffixes.pop(0)
    return "%0.2f%s" % (number, suffixes.pop(0))


def makedirs(*dirs):
    while dirs:
        if not os.path.isdir(dirs[0]):
            os.mkdir(dirs[0])
        if len(dirs) == 1:
            return dirs[0]
        dirs = [os.path.join(dirs[0], dirs[1])] + list(dirs[2:])


def _get_sdk_file(url, xpath, out_path="."):
    parts = urlparse(url)
    url_base = parts.scheme + "://" + parts.netloc + os.path.dirname(parts.path)
    xml_string = requests.get(url).content
    LOG.info("Downloaded manifest: %s (%sB)", url, si(len(xml_string)))
    root = xml.etree.ElementTree.fromstring(xml_string)
    urls = [i.text for i in root.findall(xpath)]
    assert len(urls) == 1
    tmp_fp, ziptmp = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fp)
    try:
        downloaded = 0
        with open(ziptmp, "wb") as zipf:
            response = requests.get(url_base + "/" + urls[0], stream=True)
            total_size = int(response.headers["Content-Length"])
            start_time = report_time = time.time()
            LOG.info("Downloading package: %s (%sB total)", urls[0], si(total_size))
            for chunk in response.iter_content(1024 * 1024):
                zipf.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if (now - report_time) > 30 and downloaded != total_size:
                    LOG.info(".. still downloading (%0.1f%%, %sB/s)", 100.0 * downloaded / total_size,
                             si(float(downloaded) / (now - start_time)))
                    report_time = now
        assert downloaded == total_size
        LOG.info(".. downloaded (%sB/s)", si(float(downloaded) / (time.time() - start_time)))
        with zipfile.ZipFile(ziptmp) as zipf:
            for info in zipf.infolist():
                zipf.extract(info, out_path)
                perm = info.external_attr >> 16
                perm |= stat.S_IREAD  # make sure we're not accidentally setting this to 0
                os.chmod(os.path.join(out_path, info.filename), perm)
    finally:
        os.unlink(ziptmp)


class AndroidHelper(object):

    def __init__(self, android_port=5554, avd_name=None, no_window=False, sdcard_size=500, use_snapshot=False):
        self.android_port = android_port
        self.avd_name = avd_name
        self.no_window = no_window
        self.sdcard_size = sdcard_size
        self.use_snapshot = use_snapshot

    def install(self):
        # create folder structure
        android = makedirs(HOME, ".android")
        makedirs(android, "avd")
        sdk = makedirs(android, "sdk")
        api25_gapi = makedirs(sdk, "system-images", "android-25", "google_apis")
        # this is a hack and without it for some reason the following error can happen:
        # PANIC: Cannot find AVD system path. Please define ANDROID_SDK_ROOT
        makedirs(sdk, "platforms")

        # get latest emulator for linux
        _get_sdk_file(REPO_URL,
                      ".//remotePackage[@path='emulator']"
                      "/channelRef[@ref='channel-0']/.."
                      "/archives/archive/[host-os='linux']/complete/url",
                      sdk)

        # get latest Google APIs system image
        _get_sdk_file(IMAGES_URL,
                      "./remotePackage[@path='system-images;android-25;google_apis;x86']"
                      "/channelRef[@ref='channel-0']/.."
                      "/archives/archive/complete/url",
                      api25_gapi)

        # get latest platform-tools for linux
        _get_sdk_file(REPO_URL,
                      ".//remotePackage[@path='platform-tools']"
                      "/channelRef[@ref='channel-0']/.."
                      "/archives/archive/[host-os='linux']/complete/url",
                      sdk)

    def avd(self):
        # create folder structure
        android = makedirs(HOME, ".android")
        avd_path = makedirs(android, "avd")
        sdk = os.path.join(android, "sdk")
        api25_gapi = os.path.join(sdk, "system-images", "android-25", "google_apis")

        # create an avd
        avd_ini = os.path.join(avd_path, self.avd_name + ".ini")
        assert not os.path.isfile(avd_ini)
        avd_dir = os.path.join(avd_path, self.avd_name + ".avd")
        os.mkdir(avd_dir)

        with open(avd_ini, "w") as fp:
            print("avd.ini.encoding=UTF-8", file=fp)
            print("path=" + avd_dir, file=fp)
            print("path.rel=avd/" + self.avd_name + ".avd", file=fp)
            print("target=android-25", file=fp)

        avd_cfg = os.path.join(avd_dir, "config.ini")
        assert not os.path.isfile(avd_cfg)
        with open(avd_cfg, "w") as fp:
            print("AvdId=" + self.avd_name, file=fp)
            print("PlayStore.enabled=false", file=fp)
            print("abi.type=x86", file=fp)
            print("avd.ini.displayname=" + self.avd_name, file=fp)
            print("avd.ini.encoding=UTF-8", file=fp)
            print("disk.dataPartition.size=800M", file=fp)
            print("fastboot.forceColdBoot=no", file=fp)
            print("hw.accelerometer=yes", file=fp)
            print("hw.arc=false", file=fp)
            print("hw.audioInput=yes", file=fp)
            print("hw.battery=yes", file=fp)
            print("hw.camera.back=emulated", file=fp)
            print("hw.camera.front=emulated", file=fp)
            print("hw.cpu.arch=x86", file=fp)
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
            print("hw.ramSize=3072", file=fp)
            print("hw.sdCard=yes", file=fp)
            print("hw.sensors.orientation=yes", file=fp)
            print("hw.sensors.proximity=yes", file=fp)
            print("hw.trackBall=no", file=fp)
            print("image.sysdir.1=system-images/android-25/google_apis/x86/", file=fp)
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

        shutil.copy(os.path.join(api25_gapi, "x86", "userdata.img"), avd_dir)

        sdcard = os.path.join(avd_dir, "sdcard.img")
        mksd = os.path.join(sdk, "emulator", "mksdcard")
        assert os.path.isfile(mksd)
        subprocess.check_output([mksd, "%dM" % (self.sdcard_size,), sdcard])
        shutil.copy(sdcard, sdcard + ".firstboot")

    def emulator_run(self, use_snapshot, quiet=True):
        # create folder structure
        android = makedirs(HOME, ".android")
        sdk = makedirs(android, "sdk")
        avd_path = makedirs(android, "avd")
        avd_dir = os.path.join(avd_path, self.avd_name + ".avd")
        emulator_bin = os.path.join(sdk, "emulator", "emulator")

        args = []

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

    def firstboot(self):
        # create folder structure
        android = makedirs(HOME, ".android")
        sdk = makedirs(android, "sdk")
        avd_path = makedirs(android, "avd")
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

    def kill(self):
        ctl = telnetlib.Telnet('localhost', self.android_port)

        lines = ctl.read_until('OK\r\n', 10).rstrip().splitlines()
        try:
            auth_token_idx = lines.index('Android Console: you can find your <auth_token> in ')
        except IndexError:
            pass
        else:
            auth_token_path = lines[auth_token_idx + 1].strip("'")
            with open(auth_token_path) as auth_token_fp:
                auth_token = auth_token_fp.read()
            ctl.write('auth %s\n' % (auth_token,))
            ctl.read_until('OK\r\n', 10)

        ctl.write('kill\n')
        ctl.close()

    def wait_for_boot_completed(self):
        # create folder structure
        android = makedirs(HOME, ".android")
        sdk = makedirs(android, "sdk")
        platform_tools = makedirs(sdk, "platform-tools")

        subprocess.check_output([os.path.join(platform_tools, "adb"),
                                 "wait-for-device",
                                 "shell", "while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done"],
                                timeout=60, env={"ANDROID_SERIAL": "emulator-%d" % (self.android_port,)})
        time.sleep(5)

    def run(self):
        proc = self.emulator_run(self.use_snapshot, quiet=False)
        try:
            exit_code = proc.wait()
        except Exception:
            if proc.poll() is None:
                proc.terminate()
            raise
        assert exit_code == 0, "emulator returned %d" % (exit_code,)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    aparse = argparse.ArgumentParser()
    aparse.add_argument("actions", nargs="*", choices=["avd", "install", "firstboot", "kill", "run",
                                                       "wait-for-boot-completed"])
    aparse.add_argument("--android-port", default=5554, type=int, help="Port to run emulator on (default: 5554)")
    aparse.add_argument("--avd-name", default="x86", help="Name of AVD to create/use (default: x86)")
    aparse.add_argument("--no-window", action="store_true", help="Pass -no-window to emulator")
    aparse.add_argument("--sdcard", default=500, type=int, help="SD card size in MB (default: 500)")
    aparse.add_argument("--snapshot", default="never", choices=["never", "always", "save", "load"],
                        help="Use snapshots for fast reset (default: never)")
    aparse.add_argument("--xvfb", action="store_true", help="Run emulator under XVFB")
    args = aparse.parse_args()

    if args.xvfb and {"firstboot", "run"} & set(args.actions):
        xvfb = xvfbwrapper.Xvfb(width=1280, height=1024)
    else:
        xvfb = None

    try:
        if xvfb is not None:
            xvfb.start()

        ah = AndroidHelper(args.android_port, args.avd_name, args.no_window, args.sdcard, args.snapshot)
        for action in args.actions:
            getattr(ah, action.replace("-", "_"))()
    finally:
        if xvfb is not None:
            xvfb.stop()


if __name__ == "__main__":
    main()

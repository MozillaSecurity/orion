from __future__ import print_function
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import xml.etree.ElementTree
import zipfile
import requests
from six.moves.urllib.parse import urlparse


REPO_URL = "https://dl.google.com/android/repository/repository2-1.xml"
IMAGES_URL = "https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-1.xml"

HOME = os.path.expanduser("~")

LOG = logging.getLogger("emulator_install")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def makedirs(*dirs):
    while dirs:
        if not os.path.isdir(dirs[0]):
            os.mkdir(dirs[0])
        if len(dirs) == 1:
            return dirs[0]
        dirs = [os.path.join(dirs[0], dirs[1])] + list(dirs[2:])


android = makedirs(HOME, ".android")
avd = makedirs(android, "avd")
sdk = makedirs(android, "sdk")
platforms = makedirs(sdk, "platforms")
platform_tools = makedirs(sdk, "platform-tools")
api25_gapi = makedirs(sdk, "system-images", "android-25", "google_apis")


def _get_sdk_file(url, xpath, out_path='.'):
    parts = urlparse(url)
    url_base = parts.scheme + '://' + parts.netloc + os.path.dirname(parts.path)
    xml_string = requests.get(url).content
    LOG.info("Downloaded manifest: %s (%d bytes)", url, len(xml_string))
    root = xml.etree.ElementTree.fromstring(xml_string)
    urls = [i.text for i in root.findall(xpath)]
    assert len(urls) == 1
    tmp_fp, ziptmp = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fp)
    try:
        downloaded = 0
        with open(ziptmp, "wb") as zipf:
            for chunk in requests.get(url_base + '/' + urls[0]).iter_content(1024 * 1024):
                zipf.write(chunk)
                downloaded += len(chunk)
        LOG.info("Downloaded package: %s (%d bytes)", urls[0], downloaded)
        with zipfile.ZipFile(ziptmp) as zipf:
            for info in zipf.infolist():
                zipf.extract(info, out_path)
                perm = info.external_attr >> 16
                perm |= stat.S_IREAD  # make sure we're not accidentally setting this to 0
                os.chmod(os.path.join(out_path, info.filename), perm)
    finally:
        os.unlink(ziptmp)


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

# create an avd
avd_name = "x86"
avd_ini = os.path.join(avd, avd_name + ".ini")
assert not os.path.isfile(avd_ini)
avd_dir = os.path.join(avd, avd_name + ".avd")
os.mkdir(avd_dir)

with open(avd_ini, "w") as fp:
    print("avd.ini.encoding=UTF-8", file=fp)
    print("path=" + avd_dir, file=fp)
    print("path.rel=avd/" + avd_name + ".avd", file=fp)
    print("target=android-25", file=fp)

avd_cfg = os.path.join(avd_dir, "config.ini")
assert not os.path.isfile(avd_cfg)
with open(avd_cfg, "w") as fp:
    print("AvdId=" + avd_name, file=fp)
    print("PlayStore.enabled=false", file=fp)
    print("abi.type=x86", file=fp)
    print("avd.ini.displayname=" + avd_name, file=fp)
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
    print("sdcard.size=200M", file=fp)
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
subprocess.check_output([mksd, "500M", sdcard])

# below does not work in docker build because it requires --privileged to launch an x86 emulator, since kvm is required.

#LOG.info("Initial boot to save snapshot")
#with open(os.devnull, "w") as devnull:
#    proc = subprocess.Popen([os.path.expanduser("~/.android/sdk/emulator/emulator"), "-no-window", "@" + avd_name]), stderr=devnull, stdout=devnull)
#    subprocess.check_output(['adb', 'wait-for-device', 'shell', 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'])
#    proc.terminate()
#    proc.wait()

#LOG.info("All done. Try running: `~/.android/sdk/emulator/emulator -no-snapshot-save @%s`", avd_name)

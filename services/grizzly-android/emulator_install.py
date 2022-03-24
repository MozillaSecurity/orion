# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Launch an Android Emulator on a free port."""
import argparse
import functools
import logging
import os
import platform
import random
import shutil
import socket
import subprocess
import telnetlib
import tempfile
import time
import xml.etree.ElementTree
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
from urllib.parse import urlparse

from fuzzfetch.download import download_url, get_url, iec
from fuzzfetch.extract import extract_zip

if platform.system() == "Linux":
    import xvfbwrapper


EXE_SUFFIX = ".exe" if platform.system() == "Windows" else ""
IMAGES_URL = "https://dl.google.com/android/repository/sys-img/android/sys-img2-1.xml"
LOG = logging.getLogger("emulator_install")
REPO_URL = "https://dl.google.com/android/repository/repository2-1.xml"
RETRIES = 4  # retry any failed operation this many times
RETRY_DELAY = range(15, 45)  # delay in seconds between retries
SYS_IMG = "android-30"


def init_logging(debug: bool = False) -> None:
    """Initialize logging format and level.

    Args:
        debug (bool): Enable debug logging.

    Returns:
        None
    """
    log_level = logging.INFO
    log_fmt = "[%(asctime)s] %(message)s"
    if debug:
        log_level = logging.DEBUG
        log_fmt = "%(levelname).1s %(name)s [%(asctime)s] %(message)s"
    logging.basicConfig(format=log_fmt, datefmt="%Y-%m-%d %H:%M:%S", level=log_level)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def retry(*args, **kwds) -> Callable[..., Any]:
    """Decorator that causes the function to be retried if an exception is raised.
    Can be used without arguments to accept defaults, eg. `@retry`.

    Args:
        msg (str): Error message to log if retry will be attempted. (default:
                   "Operation failed") A comma followed by the delay length and
                   exception description will be appended.
        retries (int): Number of re-tries to attempt (default: RETRIES). Note
                       that this is RE-tries, so a value of 0 will attempt the operation
                       once, a value of 1 will attempt up to twice, etc.
        errors (tuple/list): Set of exception types to handle on retry. Others will be
                             raised as normal. (default: [Exception])
        on_error (callable/None): A callback to be called if any exception is raised,
                                  eg. to cleanup between retries.

    Returns:
        callable: The wrapped function.
    """
    msg = "Operation failed"
    retries = RETRIES
    errors: Tuple[Type[BaseException], ...] = (Exception,)
    on_error = None

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def _wrapper(*sub_args: List[Any], **sub_kwds: Dict[str, Any]) -> Any:
            for remaining in range(retries, -1, -1):
                try:
                    return func(*sub_args, **sub_kwds)
                except errors as exc:  # pylint: disable=catching-non-exception
                    if on_error is not None:
                        on_error()

                    if remaining > 0:
                        delay = random.choice(RETRY_DELAY)
                        LOG.error(
                            "%s, retrying in %d seconds ('%s')", msg, delay, str(exc)
                        )
                        time.sleep(delay)
                        continue
                    raise
                except:  # noqa pylint: disable=bare-except
                    if on_error is not None:
                        on_error()
                    raise

        return _wrapper

    # if retry is used as a plain decorator, use default args
    if len(args) == 1 and not kwds and callable(args[0]):
        return _decorator(args[0])

    assert not args
    assert set(kwds.keys()) <= {"msg", "retries", "errors", "on_error"}

    msg_arg = kwds.get("msg", msg)
    assert isinstance(
        msg_arg, str
    ), f"Expected `msg` to be str, but got {type(msg_arg)!r}"
    msg = msg_arg

    retries_arg = kwds.get("retries", retries)
    assert isinstance(
        retries_arg, int
    ), f"Expected `retries` to be int, but got {type(retries_arg)!r}"
    retries = retries_arg

    errors_arg = kwds.get("errors", errors)
    assert isinstance(
        errors_arg, (tuple, list, set, frozenset)
    ), f"Expected `errors` to be iterable, but got {type(errors)!r}"
    errors = tuple(errors_arg)
    assert errors, "`errors` must not be empty."
    for exc_t in errors:
        assert issubclass(
            exc_t, BaseException
        ), f"All members of `errors` must be exception types, but got {exc_t!r}"

    on_error = kwds.get("on_error", on_error)
    if on_error is not None:
        err_t = type(on_error)
        assert callable(
            on_error
        ), f"Expected `on_error` to be callable, but got {err_t!r}"

    return _decorator


class AndroidPaths:
    """Helper to lookup Android SDK paths"""

    def __init__(
        self,
        sdk_root: Optional[Path] = None,
        prefs_root: Optional[Path] = None,
        emulator_home: Optional[Path] = None,
        avd_home: Optional[Path] = None,
    ) -> None:
        """Initialize an AndroidPaths object.

        Args:
            sdk_root (Path/None): default ANDROID_SDK_ROOT value
            prefs_root (Path/None): default ANDROID_PREFS_ROOT value
            emulator_home (Path/None): default ANDROID_EMULATOR_HOME value
            avd_home (Path/None): default ANDROID_AVD_HOME value
        """
        self._sdk_root = sdk_root
        self._prefs_root = prefs_root
        self._emulator_home = emulator_home
        self._avd_home = avd_home

    @staticmethod
    def _is_valid_sdk(path: Path) -> bool:
        return path.is_dir()

    @property
    def sdk_root(self) -> Path:
        """Look up ANDROID_SDK_ROOT

        Args:
            None

        Returns:
            Path: value of ANDROID_SDK_ROOT
        """
        if self._sdk_root is None:
            android_home_env = os.getenv("ANDROID_HOME")
            if android_home_env is not None:
                android_home = Path(android_home_env)
                if self._is_valid_sdk(android_home):
                    self._sdk_root = android_home
                    return android_home
            android_sdk_root_env = os.getenv("ANDROID_SDK_ROOT")
            if android_sdk_root_env is not None:
                self._sdk_root = Path(android_sdk_root_env)
            elif platform.system() == "Windows":
                localappdata_env = os.getenv("LOCALAPPDATA")
                assert localappdata_env is not None
                self._sdk_root = Path(localappdata_env) / "Android" / "sdk"
            elif platform.system() == "Darwin":
                self._sdk_root = Path.home() / "Library" / "Android" / "sdk"
            else:
                self._sdk_root = Path.home() / "Android" / "Sdk"
        return self._sdk_root

    @property
    def prefs_root(self) -> Path:
        """Look up ANDROID_PREFS_ROOT.

        Args:
            None

        Returns:
            Path: value of ANDROID_PREFS_ROOT
        """
        if self._prefs_root is None:
            android_prefs_root_env = os.getenv("ANDROID_PREFS_ROOT")
            android_sdk_home_env = os.getenv("ANDROID_SDK_HOME")
            if android_prefs_root_env is not None:
                self._prefs_root = Path(android_prefs_root_env)
            elif android_sdk_home_env is not None:
                self._prefs_root = Path(android_sdk_home_env)
            else:
                self._prefs_root = Path.home()
        return self._prefs_root

    @property
    def emulator_home(self) -> Path:
        """Look up ANDROID_EMULATOR_HOME

        Args:
            None

        Returns:
            Path: value of ANDROID_EMULATOR_HOME
        """
        if self._emulator_home is None:
            android_emulator_home_env = os.getenv("ANDROID_EMULATOR_HOME")
            if android_emulator_home_env is not None:
                self._emulator_home = Path(android_emulator_home_env)
            else:
                self._emulator_home = self.prefs_root / ".android"
        return self._emulator_home

    @property
    def avd_home(self) -> Path:
        """Look up ANDROID_AVD_HOME

        Args:
            None

        Returns:
            Path: value of ANDROID_AVD_HOME
        """
        if self._avd_home is None:
            android_avd_home_env = os.getenv("ANDROID_AVD_HOME")
            if android_avd_home_env is not None:
                self._avd_home = Path(android_avd_home_env)
            else:
                self._avd_home = self.emulator_home / "avd"
        return self._avd_home


class AndroidSDKRepo:
    """Android SDK repository"""

    def __init__(self, url: str) -> None:
        """Create an AndroidSDKRepo object.

        Args:
            url (str): SDK repo URL.
        """
        parts = urlparse(url)
        self.url_base = (
            parts.scheme + "://" + parts.netloc + parts.path.rsplit("/", 1)[0]
        )
        xml_string = get_url(url).content
        LOG.info("Downloaded manifest: %s (%sB)", url, iec(len(xml_string)))
        self.root = xml.etree.ElementTree.fromstring(xml_string)
        if platform.system() == "Linux":
            self.host = "linux"
        elif platform.system() == "Windows":
            self.host = "windows"
        elif platform.system() == "Darwin":
            self.host = "darwin"
        else:
            raise RuntimeError(f"Unknown platform: '{platform.system()}'")

    @staticmethod
    def read_revision(
        element: xml.etree.ElementTree.Element,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """Look for revision in an SDK package element.

        Args:
            element (Element): Package element to find revision for.

        Returns:
            tuple(int, int, int): Major, minor, micro
        """
        rev = element.find("revision")
        assert rev is not None, "No revision element found"
        major_el = rev.find("major")
        major = (
            int(major_el.text)
            if major_el is not None and major_el.text is not None
            else None
        )
        minor_el = rev.find("minor")
        minor = (
            int(minor_el.text)
            if minor_el is not None and minor_el.text is not None
            else None
        )
        micro_el = rev.find("micro")
        micro = (
            int(micro_el.text)
            if micro_el is not None and micro_el.text is not None
            else None
        )
        return (major, minor, micro)

    def get_file(
        self, package_path: str, out_path: Path, extract_package_path: bool = True
    ) -> None:
        """Install an Android SDK package.

        Args:
            package_path: xref for package in SDK XML manifest.
            out_path: Local path to extract package to.
            extract_package_path: Extract under package name from `package_path`

        Returns:
            None
        """
        package = None
        for package in self.root.findall(
            f".//remotePackage[@path='{package_path}']/channelRef[@ref='channel-0']/.."
        ):
            url = package.find(
                f"./archives/archive/[host-os='{self.host}']/complete/url"
            )
            if url is not None:
                break
            # check for the same thing without host-os
            # can't do this purely in xpath
            archive = package.find("./archives/archive/complete/url/../..")
            if archive is not None and archive.find("./host-os") is None:
                url = archive.find("./complete/url")
                if url is not None:
                    break
        else:
            raise RuntimeError(f"Package {package_path} not found!")

        # figure out where to extract package to
        path_parts = package_path.split(";")
        intermediates = path_parts[:-1]
        manifest_path = Path(out_path, *path_parts) / "package.xml"
        if not extract_package_path:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            # out_path doesn't change
        elif intermediates:
            out_path = Path(out_path, *intermediates)
            out_path.mkdir(parents=True, exist_ok=True)

        # check for an existing manifest
        if manifest_path.is_file():
            # compare the remote version with local
            remote_rev = self.read_revision(package)
            local_pkg = xml.etree.ElementTree.parse(manifest_path).find("localPackage")
            assert local_pkg is not None
            local_rev = self.read_revision(local_pkg)
            if remote_rev <= local_rev:
                fmt_rev = ".".join(
                    "" if ver is None else f"{ver:d}" for ver in local_rev
                ).strip(".")
                LOG.info(
                    "Installed %s revision %s is sufficiently new",
                    package_path,
                    fmt_rev,
                )
                return

        tmp_fp, ziptmp = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fp)
        try:
            download_url(f"{self.url_base}/{url.text}", ziptmp)
            extract_zip(ziptmp, str(out_path))
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
        license_ = package.find("uses-license")
        assert license_ is not None, "Failed to find 'uses-license' element"
        license_el = self.root.find(f"./license[@id='{license_.get('ref')}']")
        assert license_el is not None, "Failed to find 'license' element"
        manifest.append(license_el)
        local_package = xml.etree.ElementTree.SubElement(manifest, "localPackage")
        local_package.set("path", package_path)
        local_package.set("obsolete", "false")
        type_details_el = package.find("type-details")
        assert type_details_el is not None
        local_package.append(type_details_el)
        revision_el = package.find("revision")
        assert revision_el is not None
        local_package.append(revision_el)
        display_name_el = package.find("display-name")
        assert display_name_el is not None
        local_package.append(display_name_el)
        local_package.append(license_)
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
                (
                    b"<common:repository xmlns:generic="
                    b'"http://schemas.android.com/repository/android/generic/01" '
                ),
            )
        if b"xmlns:sys-img=" not in manifest_bytes and b'"sys-img:' in manifest_bytes:
            manifest_bytes = manifest_bytes.replace(
                b"<common:repository ",
                (
                    b"<common:repository xmlns:sys-img="
                    b'"http://schemas.android.com/sdk/android/repo/sys-img2/01" '
                ),
            )
        manifest_path.write_bytes(manifest_bytes)


def _is_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.05)
        sock.bind(("localhost", port))
        sock.listen(5)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            sock.close()


class AndroidEmulatorError(Exception):
    """Indicate that an error occurred during Android emulator operation."""


class AndroidEmulator:
    """Proxy for Android emulator subprocess."""

    DESC = "Android emulator"

    @retry(msg="Android emulator launch failed", errors=(AndroidEmulatorError,))
    def __init__(
        self,
        avd_name: str = "x86",
        port: int = 5554,
        snapshot: str = "never",
        env: Optional[Dict[str, str]] = None,
        xvfb: bool = False,
        target: Optional[str] = None,
        verbose: bool = False,
        avd_home: Optional[Path] = None,
    ) -> None:
        """Create an AndroidEmulator object.

        Args:
            avd_name (str): AVD machine definition name.
            port (int): ADB control port for emulator to use.
            snapshot (str): One of "never", "save", or "load". Determines snapshot
                            loading of emulator.
            env (dict): Environment variables to pass to emulator subprocess.
            xvfb (bool): Use Xvfb to launch emulator.
            target (str): The target name (from builds.json).
            verbose (bool): Enable verbose logging.
            avd_home: Where AVDs should be created.
        """
        self.avd_name = avd_name
        self.emu = None
        self.env = dict(env or {})
        self.paths = AndroidPaths(avd_home=avd_home)
        self.port = port
        self.snapshot = snapshot
        self.xvfb = None
        self.target = target
        self.verbose = verbose

        assert self.snapshot in {"never", "save", "load"}

        avd_dir = self.paths.avd_home / (self.avd_name + ".avd")

        args = []
        args.append("-writable-system")
        args.extend(("-selinux", "permissive"))
        # args.append("-no-window")

        if self.verbose:
            args.append("-verbose")

        if self.snapshot == "never":
            args.append("-no-snapshot")

        elif self.snapshot == "save":
            args.append("-no-snapshot-load")

        elif self.snapshot == "load":
            args.append("-no-snapshot-save")

            # replace sdcard with firstboot version if exists
            sdcard = avd_dir / "sdcard.img"
            sdcard_fb = avd_dir / "sdcard.img.firstboot"
            if sdcard_fb.is_file():
                if sdcard.is_file():
                    sdcard.unlink()
                shutil.copy(str(sdcard_fb), str(sdcard))

        args.extend(("-port", f"{self.port:d}"))
        args.append(f"@{self.avd_name}")

        output = (
            None
            if logging.getLogger().getEffectiveLevel() == logging.DEBUG
            else subprocess.DEVNULL
        )

        if xvfb:
            self.xvfb = xvfbwrapper.Xvfb(width=1280, height=1024)
            self.xvfb.start()

        try:
            # make a copy before we modify the passed env dictionary
            env = dict(env or {})
            if platform.system() == "Linux":
                env["DISPLAY"] = os.environ["DISPLAY"]
                if "XAUTHORITY" in os.environ:
                    env["XAUTHORITY"] = os.environ["XAUTHORITY"]
            env["ANDROID_AVD_HOME"] = str(self.paths.avd_home)

            LOG.info("Launching Android emulator with snapshot=%s", self.snapshot)
            emu = subprocess.Popen(  # pylint: disable=consider-using-with
                [str(self.paths.sdk_root / "emulator" / ("emulator" + EXE_SUFFIX))]
                + args,
                env=env,
                stderr=output,
                stdout=output,
            )
            try:
                time.sleep(5)
            except Exception:
                if emu.poll() is None:
                    emu.terminate()
                emu.wait()
                raise
            if emu.poll() is not None:
                raise AndroidEmulatorError("Failed to launch emulator")

            try:
                subprocess.check_output(
                    [
                        str(
                            self.paths.sdk_root
                            / "platform-tools"
                            / ("adb" + EXE_SUFFIX)
                        ),
                        "wait-for-device",
                        "shell",
                        (
                            "while [[ -z $(getprop sys.boot_completed) ]];"
                            "do sleep 1;"
                            "done"
                        ),
                    ],
                    timeout=60,
                    env={"ANDROID_SERIAL": f"emulator-{self.port:d}"},
                )
            except subprocess.TimeoutExpired:
                emu.terminate()
                emu.wait()
                raise AndroidEmulatorError("Emulator failed to boot in time.") from None
            except:  # noqa pylint: disable=bare-except
                emu.terminate()
                emu.wait()
                raise

            self.emu = emu
            self.pid = emu.pid

        except:  # noqa pylint: disable=bare-except
            self._stop_xvfb()
            raise

    def relaunch(self) -> None:
        """Create a new AndroidEmulator object created with the same parameters used to
        create this one.

        Args:
            None

        Return:
            AndroidEmulator: new AndroidEmulator instance.
        """
        return type(self)(
            avd_name=self.avd_name,
            port=self.port,
            snapshot=self.snapshot,
            env=self.env,
            xvfb=self.xvfb,
            target=self.target,
            verbose=self.verbose,
        )

    @staticmethod
    def install() -> None:
        """Ensure the emulator and system-image are installed.

        Args:
            None

        Returns:
            None
        """
        paths = AndroidPaths()
        LOG.info("Checking Android SDK for updates...")

        paths.sdk_root.mkdir(parents=True, exist_ok=True)
        paths.avd_home.mkdir(parents=True, exist_ok=True)

        sdk_repo = AndroidSDKRepo(REPO_URL)
        img_repo = AndroidSDKRepo(IMAGES_URL)

        # get latest emulator for linux
        sdk_repo.get_file("emulator", paths.sdk_root)

        # get latest Google APIs system image
        img_repo.get_file(
            f"system-images;{SYS_IMG};default;x86_64",
            paths.sdk_root,
        )

        # get latest platform-tools for linux
        sdk_repo.get_file("platform-tools", paths.sdk_root)

        # required for: aapt
        sdk_repo.get_file(
            "build-tools;28.0.3", paths.sdk_root, extract_package_path=False
        )

        # this is a hack and without it for some reason the following error can happen:
        # PANIC: Cannot find AVD system path. Please define ANDROID_SDK_ROOT
        (paths.sdk_root / "platforms").mkdir(exist_ok=True)

    def cleanup(self) -> None:
        """Cleanup any process files on disk.

        Args:
            None

        Returns:
            None
        """
        self.remove_avd(self.avd_name)

    def terminate(self) -> None:
        """Terminate the emulator process.

        Args:
            None

        Returns:
            None
        """
        if self.emu is not None:
            self.emu.terminate()

    def poll(self) -> Optional[int]:
        """Poll emulator process for exit status.

        Args:
            None

        Returns:
            int/None: exit status of emulator process (None if still running).
        """
        assert self.emu is not None, "No process"
        return self.emu.poll()

    def _stop_xvfb(self) -> None:
        if self.xvfb is not None:
            try:
                self.xvfb.stop()
            except Exception as exc:  # pylint: disable=broad-except
                LOG.debug("Exception %r raised stopping Xvfb", exc)
            self.xvfb = None

    def wait(self, timeout: Optional[int] = None) -> Optional[int]:
        """Wait for emulator process to exit.

        Args:
            timeout: If process does not exit within `timeout` seconds, raise
                     subprocess.TimeoutExpired.

        Returns:
            exit status of emulator process (None if still running).
        """
        assert self.emu is not None, "No process"
        result = self.emu.wait(timeout=timeout)

        if self.snapshot == "save":
            time.sleep(5)
            shutil.copy(
                str(self.paths.avd_home / (self.avd_name + ".avd") / "sdcard.img"),
                str(
                    self.paths.avd_home
                    / (self.avd_name + ".avd")
                    / "sdcard.img.firstboot"
                ),
            )

        self._stop_xvfb()
        return result

    def shutdown(self) -> None:
        """Use the emulator control channel to request clean shutdown.

        Args:
            None

        Returns:
            None
        """
        LOG.info("Initiating emulator shutdown")
        ctl = telnetlib.Telnet("localhost", self.port)

        lines = ctl.read_until(b"OK\r\n", 10).rstrip().splitlines()
        try:
            auth_token_idx = lines.index(
                b"Android Console: you can find your <auth_token> in "
            )
        except ValueError:
            pass
        else:
            auth_token_path = lines[auth_token_idx + 1].strip(b"'")
            with open(auth_token_path, "rb") as auth_token_fp:
                auth_token = auth_token_fp.read()
            ctl.write(b"auth " + auth_token + b"\n")
            ctl.read_until(b"OK\r\n", 10)

        ctl.write(b"kill\n")
        ctl.close()

    @staticmethod
    def search_free_ports(search_port: Optional[int] = None) -> int:
        """Search for a pair of adjacent free ports for use by the Android Emulator.
        The emulator uses two ports: one as a QEMU control channel, and the other for
        ADB.

        Args:
            search_port (int/None): The first port to try. Ports are attempted
                                    sequentially upwards. The default if None is given
                                    is 5554 (the usual ADB port).

        Returns:
            int: The lower port of a pair of two unused ports.
        """
        port = search_port or 5554

        # start search for 2 free ports at search_port, and look upwards sequentially
        # from there
        while port + 1 <= 0xFFFF:
            for i in range(2):
                if not _is_free(port + i):
                    # continue searching at the next untested port
                    port = port + i + 1
                    break
            else:
                return port
        raise AndroidEmulatorError("no open range could be found")

    @staticmethod
    def remove_avd(avd_name: str, avd_home: Optional[Path] = None) -> None:
        """Remove an Android emulator machine definition (AVD). No error is raised if
        the AVD doesn't exist.

        Args:
            avd_name (str): Name of AVD to remove.
            avd_home: Where AVD should be created.
        """
        paths = AndroidPaths(avd_home=avd_home)
        avd_ini = paths.avd_home / (avd_name + ".ini")
        if avd_ini.is_file():
            avd_ini.unlink()
        avd_dir = paths.avd_home / (avd_name + ".avd")
        if avd_dir.is_dir():
            shutil.rmtree(str(avd_dir))

    @classmethod
    def create_avd(
        cls, avd_name: str, sdcard_size: int = 500, avd_home: Optional[Path] = None
    ) -> None:
        """Create an Android emulator machine definition (AVD).

        Args:
            avd_name: Name of AVD to create.
            sdcard_size: Size of SD card image to use, in megabytes.
            avd_home: Where AVD should be created.
        """
        paths = AndroidPaths(avd_home=avd_home)
        mksd_path = paths.sdk_root / "emulator" / ("mksdcard" + EXE_SUFFIX)
        assert mksd_path.is_file(), f"Missing {mksd_path}"
        LOG.info("Creating AVD '%s'", avd_name)

        # create an avd
        paths.avd_home.mkdir(exist_ok=True)
        api_gapi = paths.sdk_root / "system-images" / SYS_IMG / "default"
        cls.remove_avd(avd_name)
        avd_ini = paths.avd_home / (avd_name + ".ini")
        avd_dir = paths.avd_home / (avd_name + ".avd")
        avd_dir.mkdir()

        with avd_ini.open("w") as ini:
            print("avd.ini.encoding=UTF-8", file=ini)
            print("path=" + str(avd_dir), file=ini)
            print("path.rel=avd/" + avd_name + ".avd", file=ini)
            print("target=" + SYS_IMG, file=ini)

        avd_cfg = avd_dir / "config.ini"
        assert not avd_cfg.is_file(), f"File exists '{avd_cfg}'"
        with avd_cfg.open("w") as cfg:
            print("AvdId=" + avd_name, file=cfg)
            print("PlayStore.enabled=false", file=cfg)
            print("abi.type=x86_64", file=cfg)
            print("avd.ini.displayname=" + avd_name, file=cfg)
            print("avd.ini.encoding=UTF-8", file=cfg)
            print("disk.dataPartition.size=5000M", file=cfg)
            print("fastboot.forceColdBoot=no", file=cfg)
            print("hw.accelerometer=yes", file=cfg)
            print("hw.arc=false", file=cfg)
            print("hw.audioInput=yes", file=cfg)
            print("hw.battery=yes", file=cfg)
            print("hw.camera.back=emulated", file=cfg)
            print("hw.camera.front=emulated", file=cfg)
            print("hw.cpu.arch=x86_64", file=cfg)
            print("hw.cpu.ncore=4", file=cfg)
            print("hw.dPad=no", file=cfg)
            print("hw.device.hash2=MD5:524882cfa9f421413193056700a29392", file=cfg)
            print("hw.device.manufacturer=Google", file=cfg)
            print("hw.device.name=pixel", file=cfg)
            print("hw.gps=yes", file=cfg)
            print("hw.gpu.enabled=yes", file=cfg)
            print("hw.gpu.mode=auto", file=cfg)
            print("hw.initialOrientation=Portrait", file=cfg)
            print("hw.keyboard=yes", file=cfg)
            print("hw.lcd.density=480", file=cfg)
            print("hw.lcd.height=1920", file=cfg)
            print("hw.lcd.width=1080", file=cfg)
            print("hw.mainKeys=no", file=cfg)
            print("hw.ramSize=6144", file=cfg)
            print("hw.sdCard=yes", file=cfg)
            print("hw.sensors.orientation=yes", file=cfg)
            print("hw.sensors.proximity=yes", file=cfg)
            print("hw.trackBall=no", file=cfg)
            print(f"image.sysdir.1=system-images/{SYS_IMG}/default/x86_64/", file=cfg)
            print("runtime.network.latency=none", file=cfg)
            print("runtime.network.speed=full", file=cfg)
            print(f"sdcard.size={sdcard_size:d}M", file=cfg)
            print("showDeviceFrame=no", file=cfg)
            print("skin.dynamic=yes", file=cfg)
            print("skin.name=1080x1920", file=cfg)
            print("skin.path=_no_skin", file=cfg)
            print("skin.path.backup=_no_skin", file=cfg)
            print("tag.display=Google APIs", file=cfg)
            print("tag.id=google_apis", file=cfg)
            print("vm.heapSize=256", file=cfg)

        shutil.copy(str(api_gapi / "x86_64" / "userdata.img"), str(avd_dir))

        sdcard = avd_dir / "sdcard.img"
        subprocess.check_output([str(mksd_path), f"{sdcard_size:d}M", str(sdcard)])
        shutil.copy(str(sdcard), str(sdcard) + ".firstboot")


def main(args: Optional[List[str]] = None) -> None:
    """Create and run an AVD and delete it when shutdown.

    Args:
        args (list/None): Override sys.argv (for testing).

    Returns:
        None
    """
    aparser = argparse.ArgumentParser(prog="emulator_install")
    aparser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    aparser.add_argument(
        "--skip-dl",
        "-s",
        action="store_true",
        help="Skip download/update the Android SDK and system image",
    )
    aparser.add_argument(
        "--no-launch",
        "-n",
        action="store_true",
        help="Skip creating/launching AVD",
    )
    aparser.add_argument(
        "--avd-path",
        type=Path,
        help="Change path where AVDs are created.",
    )
    argv = aparser.parse_args(args)

    debug_value = os.getenv("DEBUG", "0")
    if debug_value not in {"0", "1"}:
        raise ValueError(f"Unexpected bool value: {debug_value}")
    if debug_value == "1":
        argv.verbose = True

    init_logging(debug=argv.verbose)

    if not argv.skip_dl:
        AndroidEmulator.install()

    if not argv.no_launch:
        # Find a free port
        port = AndroidEmulator.search_free_ports()
        avd_name = f"x86.{port:d}"

        # Create an AVD and boot it once
        AndroidEmulator.create_avd(avd_name, avd_home=argv.avd_path)
        try:
            # Boot the AVD
            emu = AndroidEmulator(
                port=port,
                avd_name=avd_name,
                verbose=argv.verbose,
                avd_home=argv.avd_path,
            )
            LOG.info("Android emulator is running on port %d", port)
            try:
                emu.wait()
            finally:
                if emu.poll() is None:
                    emu.shutdown()
                emu.wait()
        finally:
            AndroidEmulator.remove_avd(avd_name, avd_home=argv.avd_path)


if __name__ == "__main__":
    main()

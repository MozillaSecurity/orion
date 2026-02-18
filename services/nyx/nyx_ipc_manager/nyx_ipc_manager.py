# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from argparse import REMAINDER, ArgumentParser
from pathlib import Path, PurePosixPath
from random import choice, randint
from subprocess import TimeoutExpired, run
from typing import TYPE_CHECKING

from ffpuppet.profile import Profile

if TYPE_CHECKING:
    from io import TextIOBase


def run_generic(
    args: list[str],
    bindir: Path,
    cache_path: Path,
    min_msg_size: int,
    ignore_message_types: set[str],
    timeout: int,
) -> dict[str, int]:
    unique_msgs = {}

    env = os.environ.copy()

    env["LD_LIBRARY_PATH"] = str(bindir)
    env["NYX_FUZZER"] = "IPC_SingleMessage"
    env["AFL_IGNORE_PROBLEMS"] = "1"

    if cache_path.is_file():
        with cache_path.open() as fd:
            unique_msgs = json.load(fd)
    else:
        try:
            process = run(
                args,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                start_new_session=True,
            )
            out = process.stdout or ""
            err = process.stderr or ""
        except TimeoutExpired as exc:
            out = (exc.stdout or b"").decode("utf-8")
            err = (exc.stderr or b"").decode("utf-8")

        # 1:02.58 GECKO(541198) INFO:
        # INFO: [OnIPCMessage] Message: \
        # PBackgroundIDBFactory::Msg_PBackgroundIDBDatabaseConstructor Size: 576
        errlines = out.splitlines()
        errlines.extend(err.splitlines())
        maybe_too_small: set[str] = set()
        for errline in errlines:
            if "[OnIPCMessage]" in errline and "unknown IPC msg name" not in errline:
                components = errline.split(" ")
                msize = int(components[-1])
                mtype = components[-3]

                if mtype in unique_msgs:
                    if msize >= min_msg_size and mtype in maybe_too_small:
                        maybe_too_small.remove(mtype)
                    unique_msgs[mtype] = unique_msgs[mtype] + 1
                else:
                    if msize < min_msg_size:
                        maybe_too_small.add(mtype)
                    unique_msgs[mtype] = 1

        for mtype in maybe_too_small:
            del unique_msgs[mtype]

        with cache_path.open("w") as fd:
            json.dump(unique_msgs, fd)

    for msgtype in ignore_message_types:
        if msgtype in unique_msgs:
            del unique_msgs[msgtype]

    return unique_msgs


def run_mochitest_local(
    bindir: Path,
    testenv: Path,
    mochitest_args: list[str],
    mochitest_cache_path: Path,
    min_msg_size: int,
    ignore_message_types: set[str],
) -> dict[str, int]:
    args = [
        str(testenv / "venv" / "bin" / "python"),
        "-u",
        str(testenv / "tests" / "mochitest" / "runtests.py"),
        *mochitest_args,
        "--setpref=network.process.enabled=false",
        "--setpref=webgl.force-enabled=true",
        "--setpref=gfx.webgpu.force-enabled=true",
        "--marionette-startup-timeout=180",
        "--log-mach=-",
        f"--sandbox-read-whitelist={testenv}",
        f"--appname={bindir / 'firefox'}",
        f"--utility-path={testenv / 'tests' / 'bin'}",
        f"--extra-profile-file={testenv / 'tests' / 'bin' / 'plugins'}",
        f"--certificate-path={testenv / 'tests' / 'certs'}",
    ]

    return run_generic(
        args, bindir, mochitest_cache_path, min_msg_size, ignore_message_types, 600
    )


def run_file_local(
    bindir: Path,
    sharedir: Path,
    local_file: Path,
    local_file_cache_path: Path,
    min_msg_size: int,
    ignore_message_types: set[str],
) -> dict[str, int]:
    prefs_file = sharedir / "prefs.js"
    firefox_path = bindir / "firefox"

    with Profile(prefs_file=prefs_file, working_path=str(Path.cwd())) as profile:
        args = [
            str(firefox_path),
            "-P",
            str(profile.path),
            f"file://{PurePosixPath(local_file)}",
        ]
        return run_generic(
            args, bindir, local_file_cache_path, min_msg_size, ignore_message_types, 30
        )


def add_nyx_env_vars(fd: TextIOBase) -> None:
    """Add env vars prefixed MOZ_FUZZ_ to config.sh which is
    passed through to the QEMU target.
    """
    for env, value in os.environ.items():
        if env.startswith("MOZ_FUZZ_") and env not in {
            "MOZ_FUZZ_IPC_TRIGGER",
            "MOZ_FUZZ_IPC_TRIGGER_SINGLEMSG_WAIT",
        }:
            print(f'export {env}="{value}"', file=fd)


def run_afl(
    aflbinpath: Path,
    afldir: Path,
    sharedir: Path,
    runtime: int,
    custom_mutator: str | None,
    debug: bool,
) -> None:
    env = os.environ.copy()

    # env["AFL_NO_UI"] = "1"
    env["AFL_IMPORT_FIRST"] = "1"
    env["AFL_AUTORESUME"] = "1"
    env["AFL_NYX_AUX_SIZE"] = "65536"
    env["AFL_NYX_LOG"] = str(afldir / "nyx.log")
    env["AFL_NO_STARTUP_CALIBRATION"] = "1"
    if custom_mutator is not None:
        env["AFL_CUSTOM_MUTATOR_LIBRARY"] = custom_mutator

    args = [
        str(aflbinpath),
        "-t",
        "30000",
        "-i",
        str(afldir / "in"),
        "-o",
        str(afldir / "out"),
        "-Y",
        "-M",
        "0",
        "-F",
        str(afldir / "out" / "workdir" / "dump" / "seeds"),
        str(sharedir),
    ]

    dry_run = False

    if not dry_run:
        try:
            run(args, env=env, start_new_session=True, timeout=runtime)
        except (TimeoutExpired, KeyboardInterrupt):
            pass

    snapshot_dir = afldir / "out" / "workdir" / "snapshot"
    if (snapshot_dir / "global.state").is_file():
        # Clean snapshot to save space
        shutil.rmtree(snapshot_dir)
    elif not debug:
        # Failed run, remove directory
        shutil.rmtree(afldir)


def main(args: list[str] | None = None) -> int:
    """Command line options."""

    # setup argparser
    parser = ArgumentParser()

    # Generic information
    parser.add_argument(
        "--sharedir", required=True, help="Nyx sharedir", metavar="DIR", type=Path
    )

    # Targets
    target_group = parser.add_argument_group(
        "Targets", "A single target must be selected."
    )
    targets = target_group.add_mutually_exclusive_group(required=True)
    targets.add_argument(
        "--mochitest",
        help="Run a specific mochitest flavor (plain, browser or chrome)",
        metavar="FLAVOR",
    )
    targets.add_argument(
        "--file", help="Run a specific file directly", metavar="FILE", type=Path
    )

    # Fuzzing Mode
    fuzzing_mode_group = parser.add_argument_group(
        "Fuzzing Mode", "A single fuzzing mode must be selected."
    )
    fuzzing_mode = fuzzing_mode_group.add_mutually_exclusive_group(required=True)
    fuzzing_mode.add_argument(
        "--single", action="store_true", help="Run the IPC_SingleMessage fuzzer"
    )
    fuzzing_mode.add_argument(
        "--generic", action="store_true", help="Run the IPC_Generic fuzzer"
    )

    # Fuzzing Mode options
    parser.add_argument(
        "--single-trigger",
        help="Use specified trigger message instead of randomly selecting one",
        metavar="NAME",
    )
    parser.add_argument(
        "--single-trigger-filter",
        help="Select a trigger containing the specified substring.",
        metavar="NAME",
    )
    parser.add_argument(
        "--single-skip",
        type=int,
        help="Skip the specified number of trigger messages instead of randomly "
        "deciding",
        metavar="NAME",
    )
    parser.add_argument(
        "--single-max-skip",
        type=int,
        help="Maximum amount of skips when deciding randomly.",
        metavar="NAME",
    )
    parser.add_argument(
        "--single-minsize",
        default=256,
        type=int,
        help="Minimum message size to consider in single mode.",
        metavar="SIZE",
    )
    parser.add_argument(
        "--single-ignore-messages",
        help="File with a set of messages to ignore",
        metavar="FILE",
        type=Path,
    )
    parser.add_argument(
        "--generic-trigger",
        help="Use the specified trigger message instead of the default one",
        metavar="NAME",
    )
    parser.add_argument(
        "--generic-protofilter",
        help="Use the specified protocol filter",
        metavar="NAME",
    )

    # Mochitest options
    parser.add_argument(
        "--mochitest-manifest", help="Run a specific mochitest manifest", metavar="NAME"
    )
    parser.add_argument(
        "--mochitest-subsuite", help="Run a specific mochitest subsuite", metavar="NAME"
    )

    # File options
    parser.add_argument(
        "--file-zip",
        help="Name of the zip file containing the target page",
        default="page.zip",
        metavar="FILE",
    )

    # AFL-related
    parser.add_argument(
        "--afl",
        help="Start an AFL instance with the specified working prefix.",
        metavar="DIR",
    )
    parser.add_argument(
        "--write-corpus",
        help="Write a corpus to the specified directory.",
        metavar="DIR",
    )

    parser.add_argument("rargs", nargs=REMAINDER)

    # process options
    opts = parser.parse_args(args=args)

    bindir = opts.sharedir / "firefox"
    testenv = opts.sharedir / "testenv"

    ignore_message_types = set()
    if opts.single_ignore_messages is not None:
        with opts.single_ignore_messages.open() as fd:
            ignore_message_types |= {line.strip() for line in fd}

    mochitest_dir: Path | None = None
    if opts.mochitest is not None:
        if opts.mochitest == "plain":
            mochitest_dir = testenv / "tests" / "mochitest" / "tests"
        elif opts.mochitest == "browser":
            mochitest_dir = testenv / "tests" / "mochitest" / "browser"
        elif opts.mochitest == "chrome":
            mochitest_dir = testenv / "tests" / "mochitest" / "chrome"
        else:
            print("Error: Invalid argument for --mochitest-manifest", file=sys.stderr)
            return 1
        assert mochitest_dir is not None

        mochitest_manifest = None
        mochitest_subsuite = None

        if opts.mochitest_manifest is not None:
            mochitest_manifest = opts.mochitest_manifest
            if (
                not mochitest_manifest.is_file()
                and (mochitest_dir / mochitest_manifest).is_file()
            ):
                mochitest_manifest = mochitest_dir / mochitest_manifest
        else:
            # Randomly select a manifest
            manifest_name = {
                "plain": "mochitest.ini",
                "browser": "browser.ini",
                "chrome": "chrome.ini",
            }

            mochitest_list = list(
                mochitest_dir.glob(f"**/{manifest_name[opts.mochitest]}")
            )
            mochitest_manifest = choice(mochitest_list)

        print(f"Selected Mochitest Manifest: {mochitest_manifest}")

        if opts.mochitest_subsuite is not None:
            mochitest_subsuite = opts.mochitest_subsuite
        else:
            available_subsuites = []
            with mochitest_manifest.open() as manifest_fd:
                lines = manifest_fd.readlines()
                for line in lines:
                    if line.startswith("subsuite ="):
                        (_, subsuite) = line.split("=")
                        available_subsuites.append(subsuite.strip())

            if available_subsuites:
                mochitest_subsuite = choice(available_subsuites)

        mochitest_args = [mochitest_manifest, f"--flavor={opts.mochitest}"]
        if mochitest_subsuite is not None:
            mochitest_args.append(f"--subsuite={mochitest_subsuite}")
            mochitest_cache_path = Path(
                f"{mochitest_manifest}.{mochitest_subsuite}.cache.json"
            )
        else:
            mochitest_cache_path = Path(f"{mochitest_manifest}.cache.json")

        if opts.single:
            single_trigger = opts.single_trigger
            single_trigger_filter = opts.single_trigger_filter
            single_max_skip = opts.single_max_skip
            single_skip = opts.single_skip

            # Perform a local run to gather all messages
            unique_msgs = run_mochitest_local(
                bindir,
                testenv,
                mochitest_args,
                mochitest_cache_path,
                opts.single_minsize,
                ignore_message_types,
            )

            if single_trigger is None:
                if single_trigger_filter is not None:
                    msg_list = []
                    for msg in unique_msgs:
                        if single_trigger_filter in msg:
                            msg_list.append(msg)
                else:
                    msg_list = list(unique_msgs)
                single_trigger = choice(msg_list)
            else:
                if single_trigger not in unique_msgs:
                    print(
                        "ERROR: Trigger message not detected in local run!",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            if single_skip is None:
                if single_max_skip is None:
                    single_max_skip = unique_msgs[single_trigger] - 1
                else:
                    single_max_skip = min(
                        single_max_skip, unique_msgs[single_trigger] - 1
                    )
                single_skip = randint(0, single_max_skip)

            print(
                f"Single Message Fuzzing Mode - Selected {single_trigger} with "
                f"{single_skip} skips"
            )

            with (opts.sharedir / "config.sh").open("w") as fd:
                print(f'export MOZ_FUZZ_IPC_TRIGGER="{single_trigger}"', file=fd)
                print(
                    f'export MOZ_FUZZ_IPC_TRIGGER_SINGLEMSG_WAIT="{single_skip}"',
                    file=fd,
                )
                print('export NYX_FUZZER="IPC_SingleMessage"', file=fd)
                mochitest_arg_str = " ".join(mochitest_args)
                print(f'export MOCHITEST_ARGS="{mochitest_arg_str}"', file=fd)
                add_nyx_env_vars(fd)
        else:
            with (opts.sharedir / "config.sh").open("w") as fd:
                print('export NYX_FUZZER="IPC_Generic"', file=fd)
                mochitest_arg_str = " ".join(mochitest_args)
                print(f'export MOCHITEST_ARGS="{mochitest_arg_str}"', file=fd)
                add_nyx_env_vars(fd)

    elif opts.file is not None:
        # Run with a local page instead of mochitests
        if opts.single:
            single_trigger = opts.single_trigger
            single_trigger_filter = opts.single_trigger_filter
            single_max_skip = opts.single_max_skip
            single_skip = opts.single_skip

            local_file_cache_path = Path(f"{opts.file}.cache.json")

            # Perform a local run to gather all messages
            unique_msgs = run_file_local(
                bindir,
                opts.sharedir,
                opts.file,
                local_file_cache_path,
                opts.single_minsize,
                ignore_message_types,
            )

            if single_trigger is None:
                if single_trigger_filter is not None:
                    msg_list = []
                    for msg in unique_msgs:
                        if single_trigger_filter in msg:
                            msg_list.append(msg)
                else:
                    msg_list = list(unique_msgs)
                single_trigger = choice(msg_list)
            else:
                if single_trigger not in unique_msgs:
                    print(
                        "ERROR: Trigger message not detected in local run!",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            if single_skip is None:
                if single_max_skip is None:
                    single_max_skip = unique_msgs[single_trigger] - 1
                else:
                    single_max_skip = min(
                        single_max_skip, unique_msgs[single_trigger] - 1
                    )
                single_skip = randint(0, single_max_skip)

            print(
                f"Single Message Fuzzing Mode - Selected {single_trigger} with "
                f"{single_skip} skips"
            )

            with (opts.sharedir / "config.sh").open("w") as fd:
                print(f'export MOZ_FUZZ_IPC_TRIGGER="{single_trigger}"', file=fd)
                print(
                    f'export MOZ_FUZZ_IPC_TRIGGER_SINGLEMSG_WAIT="{single_skip}"',
                    file=fd,
                )
                print('export NYX_FUZZER="IPC_SingleMessage"', file=fd)
                print(f'export NYX_PAGE="{opts.file_zip}"', file=fd)
                print(
                    f'export NYX_PAGE_HTMLNAME="{opts.file.name}"',
                    file=fd,
                )
                add_nyx_env_vars(fd)
        else:
            with (opts.sharedir / "config.sh").open("w") as fd:
                print('export NYX_FUZZER="IPC_Generic"', file=fd)
                print(f'export NYX_PAGE="{opts.file_zip}"', file=fd)
                print(
                    f'export NYX_PAGE_HTMLNAME="{opts.file.name}"',
                    file=fd,
                )
                add_nyx_env_vars(fd)

        if opts.write_corpus is not None or opts.afl is not None:
            if opts.single:
                single_trigger_sanitized = single_trigger.replace(":", "_")

                if opts.afl is None:
                    samples_destdir = opts.write_corpus
                else:
                    afldir = Path(
                        f"{opts.afl}.{hashlib.sha1(single_trigger_sanitized.encode('utf-8')).hexdigest()}"
                    )
                    if not afldir.is_dir():
                        (afldir / "in").mkdir(parents=True)
                        shutil.copy(opts.sharedir / "config.sh", afldir / "config.sh")

                        if opts.samples is not None:
                            samples_destdir = afldir / "in"
                        else:
                            # Make sure we start with a non-empty corpus, otherwise
                            # AFL++ will not start up
                            with (afldir / "in" / "input0").open("w") as outfd:
                                print("Hello world", file=outfd)

                if opts.samples is not None and samples_destdir is not None:
                    for data in opts.samples.glob(f"{single_trigger_sanitized}*.bin"):
                        shutil.copy(data, samples_destdir)
            elif opts.generic:
                # TODO: Implement copy/transform algorithm for IPC_Generic
                pass

            # if opts.afl is not None:
            #     run_afl()

    return 0


if __name__ == "__main__":
    sys.exit(main())

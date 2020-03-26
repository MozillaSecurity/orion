#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

import fasteners


TOKEN_PATH = pathlib.Path(tempfile.gettempdir()) / "rwait"


class RemoteWait:
    def __init__(self, token=None):
        self._token = None
        if token is not None:
            self.token = token

    @property
    def _token_file(self):
        return TOKEN_PATH / self.token

    @property
    def token(self):
        assert self._token is not None, "token has not been created/set"
        return self._token

    @token.setter
    def token(self, value):
        assert self._token is None, "token already has a value"
        self._token = value

    def new(self):
        self.token = str(uuid.uuid4())
        TOKEN_PATH.mkdir(exist_ok=True)
        with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
            assert not self._token_file.is_file()
            self._token_file.write_text(json.dumps({"state": "new"}))

    def run(self, cmd):
        with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
            data = json.loads(self._token_file.read_text())
            assert data["state"] == "new"
            try:
                proc = subprocess.Popen(cmd)
            except:  # noqa pylint: disable=bare-except
                data["state"] = "done"
                data["result"] = 1
                self._token_file.write_text(json.dumps(data))
                raise
            data["state"] = "running"
            data["pid"] = proc.pid
            self._token_file.write_text(json.dumps(data))
        result = proc.wait()
        with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
            data["state"] = "done"
            data["result"] = result
            self._token_file.write_text(json.dumps(data))
        return result

    def poll(self):
        """Return 0 while program is pre-run or running, 1 if program is exited
        """
        with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
            data = json.loads(self._token_file.read_text())
        return 0 if data["state"] in {"new", "running"} else 1

    def wait(self):
        """Hang until target exits, then return its exit code.
        """
        is_pid1 = (os.getpid() == 1)
        while True:
            with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
                data = json.loads(self._token_file.read_text())
            if data["state"] == "done":
                break
            if is_pid1:
                # wait for any child processes
                while os.waitpid(-1, os.WNOHANG) != (0, 0):
                    pass
            time.sleep(1)
        return data["result"]

    def delete(self):
        """Remove resources used by the token.
        """
        with fasteners.InterProcessLock(str(self._token_file) + ".lck"):
            self._token_file.unlink()
        (self._token_file.parent / (self._token_file.stem + ".lck")).unlink()

    def __str__(self):
        return self.token

    @staticmethod
    def arg_parser():
        parser = argparse.ArgumentParser(prog="rwait")
        parser.set_defaults(token=None)
        subparsers = parser.add_subparsers(dest="subcommand")
        subparsers.add_parser("create", help="create an rwait token")
        run_parser = subparsers.add_parser(
            "run", help="run a command using rwait token for result status",
        )
        run_parser.add_argument("token", help="rwait token")
        run_parser.add_argument(
            "command", nargs=argparse.REMAINDER, help="command to run",
        )
        poll_parser = subparsers.add_parser("poll", help="poll an rwait token")
        poll_parser.add_argument("token", help="rwait token")
        wait_parser = subparsers.add_parser("wait", help="wait on an rwait token",)
        wait_parser.add_argument("token", help="rwait token")
        rm_parser = subparsers.add_parser("rm", help="delete an rwait token")
        rm_parser.add_argument("token", help="rwait token")
        return parser

    @classmethod
    def main(cls, args=None):
        parser = cls.arg_parser()
        args = parser.parse_args(args)
        rwait = cls(args.token)
        if args.subcommand == "run":
            sys.exit(rwait.run(args.command))
        if args.subcommand == "poll":
            sys.exit(rwait.poll())
        if args.subcommand == "wait":
            sys.exit(rwait.wait())
        if args.subcommand == "create":
            rwait.new()
            print(rwait)
            sys.exit(0)
        if args.subcommand == "rm":
            rwait.delete()
            sys.exit(0)
        parser.error(f"unknown subcommand: {args.subcommand}")


if __name__ == "__main__":
    RemoteWait.main()

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import sys
from argparse import ArgumentParser

import psutil
from google.cloud import storage


def ncpu() -> None:
    print(psutil.cpu_count(logical=False))


def gcs_cat() -> None:
    parser = ArgumentParser(prog="gcs-cat")
    parser.add_argument("bucket")
    parser.add_argument("path")
    args = parser.parse_args()

    client = storage.Client()
    bucket = client.bucket(args.bucket)

    blob = bucket.blob(args.path)
    print(f"Downloading gs://{args.bucket}/{args.path}", file=sys.stderr)
    with os.fdopen(sys.stdout.fileno(), "wb", closefd=False) as stdout:
        blob.download_to_file(stdout)

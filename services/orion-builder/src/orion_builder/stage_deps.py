# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Stage build deps Orion builder"""


import argparse
from pathlib import Path
from shutil import copyfileobj, rmtree
from subprocess import Popen, check_call
from tempfile import mkdtemp, mkstemp
from types import TracebackType
from typing import List, Optional, Type

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Img, patch_dockerfile
from taskboot.target import Target
from taskboot.utils import download_artifact, load_artifacts

from .cli import BaseArgs, configure_logging

CA_KEY = Path.home() / "cakey.pem"
CA_CRT = Path.home() / "ca.pem"
SRV_KEY = Path.home() / "srvkey.pem"
SRV_CRT = Path.home() / "srv.pem"


def create_cert(
    key_path: Path,
    cert_path: Path,
    ca: bool = False,
    ca_key: Optional[Path] = None,
    ca_cert: Optional[Path] = None,
) -> None:
    """Create a self-signed localhost certificate. If a CA certificate is created,
    install in the system ca-certificate store.

    Arguments:
        key_path: output path for key
        cert_path: output path for certificate
        ca: whether or not the certificate is a CA root
        ca_key: CA root key to sign the created cert
        ca_cert: CA root certificate to sign the created cert
    """
    if ca:
        assert ca_key is None and ca_cert is None, "Can't give ca_key/cert when ca=True"
    tmpd = Path(mkdtemp(prefix="create-cert-"))
    try:
        csr = tmpd / "cert.req"
        ext = tmpd / "cert.ext"
        check_call(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(csr),
                "-subj",
                "/CN=localhost",
            ]
        )
        ext.write_text(
            "authorityKeyIdentifier = keyid,issuer\n"
            f"basicConstraints = CA:{str(ca).upper()}\n"
            "subjectKeyIdentifier = hash\n"
            "subjectAltName = @alt_names\n"
            "\n"
            "[alt_names]\n"
            "DNS.1 = localhost\n"
            "IP.1 = 127.0.0.1\n"
        )
        cmd = [
            "openssl",
            "x509",
            "-req",
            "-sha256",
            "-days",
            "1",
            "-in",
            str(csr),
            "-out",
            str(cert_path),
            "-extfile",
            str(ext),
        ]
        if ca_key and ca_cert:
            cmd.extend(
                [
                    "-CA",
                    str(ca_cert),
                    "-CAkey",
                    str(ca_key),
                    "-CAcreateserial",
                ]
            )
        else:
            cmd.extend(
                [
                    "-signkey",
                    str(key_path),
                ]
            )
        check_call(cmd)
    finally:
        rmtree(tmpd)
    if ca:
        store_fd, store_path_str = mkstemp(
            dir="/usr/share/ca-certificates", prefix="localhost-", suffix=".crt"
        )
        store_path = Path(store_path_str)
        with cert_path.open() as cert_fd, open(store_fd, "w") as store_fd2:
            copyfileobj(cert_fd, store_fd2)
        with Path("/etc/ca-certificates.conf").open("a") as ca_cnf:
            print(store_path.name, file=ca_cnf)
        check_call(["update-ca-certificates"])


class Registry:
    """Docker registry at localhost."""

    def __init__(self) -> None:
        self.proc = Popen(
            ["registry", "serve", "/root/registry.yml"],
            env={
                "REGISTRY_LOG_ACCESSLOG_DISABLED": "true",
                "REGISTRY_LOG_LEVEL": "warn",
                "REGISTRY_HTTP_ADDR": "0.0.0.0:443",
                "REGISTRY_HTTP_TLS_CERTIFICATE": str(SRV_CRT),
                "REGISTRY_HTTP_TLS_KEY": str(SRV_KEY),
            },
        )

    def __enter__(self) -> "Registry":
        return self

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc_value: Optional[BaseException],
        _exc_traceback: Optional[TracebackType],
    ) -> None:
        self.proc.kill()
        self.proc.wait()
        rmtree("/var/lib/registry", ignore_errors=True)


def stage_deps(target: Target, args: argparse.Namespace) -> None:
    """Pull image dependencies into the `img` store.

    Arguments:
        target: Target
        args: CLI arguments
    """
    create_cert(CA_KEY, CA_CRT, ca=True)
    create_cert(SRV_KEY, SRV_CRT, ca_key=CA_KEY, ca_cert=CA_CRT)
    img_tool = Img(cache=args.cache)

    # retrieve image archives from dependency tasks to /images
    image_path = Path(mkdtemp(prefix="image-deps-"))
    try:
        config = Configuration(argparse.Namespace(secret=None, config=None))
        queue = taskcluster.Queue(config.get_taskcluster_options())

        # load images into the img image store via Docker registry
        with Registry():
            for task_id, artifact_name in load_artifacts(
                args.task_id, queue, "public/**.tar.zst"
            ):
                img = download_artifact(queue, task_id, artifact_name, image_path)
                image_name = Path(artifact_name).name[: -len(".tar.zst")]
                check_call(
                    [
                        "skopeo",
                        "copy",
                        f"docker-archive:{img}",
                        f"docker://localhost/mozillasecurity/{image_name}:latest",
                    ]
                )
                img.unlink()
                img_tool.run(["pull", f"localhost/mozillasecurity/{image_name}:latest"])
                img_tool.run(
                    [
                        "tag",
                        f"localhost/mozillasecurity/{image_name}:latest",
                        f"{args.registry}/mozillasecurity/{image_name}:latest",
                    ]
                )
                img_tool.run(
                    [
                        "tag",
                        f"localhost/mozillasecurity/{image_name}:latest",
                        (
                            f"{args.registry}/mozillasecurity/"
                            f"{image_name}:{args.git_revision}"
                        ),
                    ]
                )
    finally:
        rmtree(image_path)

    # workaround https://github.com/genuinetools/img/issues/206
    patch_dockerfile(target.check_path(args.dockerfile), img_tool.list_images())


def registry_main(argv: Optional[List[str]] = None) -> None:
    """Registry entrypoint. Does not return."""
    args = BaseArgs.parse_args(argv)
    configure_logging(level=args.log_level)
    if not CA_KEY.is_file():
        create_cert(CA_KEY, CA_CRT, ca=True)
    if not SRV_KEY.is_file():
        create_cert(SRV_KEY, SRV_CRT, ca_key=CA_KEY, ca_cert=CA_CRT)
    with Registry() as reg:
        reg.proc.wait()

# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Stage build deps Orion builder"""
from argparse import Namespace
from pathlib import Path
from shutil import copyfile, rmtree
from subprocess import Popen, check_call
from tempfile import mkdtemp

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Img, patch_dockerfile
from taskboot.utils import load_artifacts, download_artifact


CA_KEY = Path.home() / "cakey.pem"
CA_CRT = Path.home() / "ca.pem"
SRV_REQ = Path.home() / "srvreq.csr"
SRV_KEY = Path.home() / "srvkey.pem"
SRV_CRT = Path.home() / "srv.pem"


def create_cert():
    """Create a self-signed server certificate at `SRV_CRT` (key `SRV_KEY`)
    and install the CA certificate (`CA_CRT`) in the machines ca-certificate store.

    Returns:
        None
    """
    # create a self-signed server cert
    # in /root/srv.pem & key in /root/srvkey.pem
    # & install the CA cert
    # expires in 1 day
    check_call(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-sha256",
            "-keyout",
            str(CA_KEY),
            "-out",
            str(CA_CRT),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ]
    )
    check_call(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:4096",
            "-sha256",
            "-keyout",
            str(SRV_KEY),
            "-out",
            str(SRV_REQ),
            "-nodes",
            "-subj",
            "/CN=localhost",
        ]
    )
    check_call(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(SRV_REQ),
            "-sha256",
            "-CA",
            str(CA_CRT),
            "-CAkey",
            str(CA_KEY),
            "-CAcreateserial",
            "-out",
            str(SRV_CRT),
            "-days",
            "1",
        ]
    )
    copyfile(CA_CRT, "/usr/share/ca-certificates/localhost.crt")
    with Path("/etc/ca-certificates.conf").open("a") as ca_cnf:
        print("localhost.crt", file=ca_cnf)
    check_call(["update-ca-certificates"])


class Registry:
    """Docker registry at localhost."""

    def __init__(self):
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

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _exc_traceback):
        self.proc.kill()
        self.proc.wait()
        rmtree("/var/lib/registry")


def stage_deps(args):
    """Pull image dependencies into the `img` store.

    Arguments:
        args (argparse.Namespace): CLI arguments

    Returns:
        None
    """
    create_cert()
    img_tool = Img(cache=args.cache)

    # retrieve image archives from dependency tasks to /images
    image_path = Path(mkdtemp(prefix="image-deps-"))
    try:
        config = Configuration(Namespace(secret=None, config=None))
        queue = taskcluster.Queue(config.get_taskcluster_options())

        # load images into the img image store via Docker registry
        for task_id, artifact_name in load_artifacts(
            args.task_id, queue, "public/**.tar"
        ):
            img = download_artifact(queue, task_id, artifact_name, image_path)
            image_name = Path(artifact_name).stem
            with Registry():
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
    patch_dockerfile(args.dockerfile, img_tool.list_images())

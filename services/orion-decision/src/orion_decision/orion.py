# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Orion service definitions"""
from logging import getLogger
from platform import machine
import re

from dockerfile_parse import DockerfileParser
from yaml import safe_load as yaml_load


LOG = getLogger(__name__)


class Service:
    """Orion service (Docker image)

    Attributes:
        dockerfile (Path): Path to the Dockerfile
        context (Path): build context
        name (str): Image name (Docker tag)
        service_deps (set(str)): Names of images that this one depends on.
        path_deps (set(Path)): Paths that this image depends on.
        dirty (bool): Whether or not this image needs to be rebuilt
    """

    def __init__(self, dockerfile, context, name):
        """Initialize a Service instance.

        Arguments:
            dockerfile (Path): Path to the Dockerfile
            context (Path): build context
            name (str): Image name (Docker tag)
        """
        self.dockerfile = dockerfile
        self.context = context
        self.name = name
        self.service_deps = set()
        self.path_deps = set()
        self.dirty = False

    @classmethod
    def from_metadata_yaml(cls, metadata, context):
        """Create a Service instance from a service.yaml metadata path.

        Arguments:
            metadata (Path): Path to a service.yaml file.
            context (Path): The context from which this service is built.

        Returns:
            Service: A service instance.
        """
        metadata_path = metadata
        metadata = yaml_load(metadata_path.read_text())
        name = metadata["name"]
        LOG.info("Loading %s from %s", name, metadata_path)
        cpu = {"x86_64": "amd64"}.get(machine(), machine())
        if (
            "arch" in metadata
            and cpu in metadata["arch"]
            and "dockerfile" in metadata["arch"][cpu]
        ):
            dockerfile = metadata_path.parent / metadata["arch"][cpu]["dockerfile"]
        else:
            dockerfile = metadata_path.parent / "Dockerfile"
        assert dockerfile.is_file()
        return cls(dockerfile, context, name)


class Services(dict):
    """Collection of Orion Services.

    Attributes:
        services (dict(str -> Service)): Mapping of service name (`service.name`) to
                                         the `Service` instance.
        root (Path): The root for loading services and watching recipe scripts.
    """

    def __init__(self, root):
        """Initialize a `Services` instances.

        Arguments:
            root (Path): The root for loading services and watching recipe scripts.
        """
        super().__init__()
        self.root = root
        # scan the context recursively to find services
        for service_yaml in self.root.glob("**/service.yaml"):
            service = Service.from_metadata_yaml(service_yaml, self.root)
            assert service.name not in self
            service.path_deps |= {service_yaml, service.dockerfile}
            self[service.name] = service
        self._calculate_depends()

    def _calculate_depends(self):
        """Go through each service and try to determine what dependencies it has.

        There are two types of dependencies:
        - service: The base image used for the dockerfile (only for `mozillasecurity/`)
        - paths: Files in the same root thatare used by the image.

        Returns:
            None
        """
        # make a list of all file paths
        file_strs = []
        for file in self.root.glob("**/*"):
            if "tests" in file.relative_to(self.root).parts:
                continue
            if not file.is_file():
                continue
            file_strs.append(str(file.relative_to(self.root)))
            LOG.debug("found path: %s", file_strs[-1])
        file_re = re.compile("|".join(re.escape(file) for file in file_strs))

        for service in self.values():
            # calculate image dependencies
            parser = DockerfileParser(path=str(service.dockerfile))
            if parser.baseimage is not None and parser.baseimage.startswith(
                "mozillasecurity/"
            ):
                baseimage = parser.baseimage.split("/", 1)[1]
                if ":" in baseimage:
                    baseimage = baseimage.split(":", 1)[0]
                assert baseimage in self
                service.service_deps.add(baseimage)
                LOG.info("Image %s depends on image %s", service.name, baseimage)

            # scan service for references to files
            for entry in service.dockerfile.parent.glob("**/*"):
                if not entry.is_file():
                    continue
                try:
                    entry_text = entry.read_text()
                except UnicodeError:
                    continue
                for match in file_re.finditer(entry_text):
                    path = self.root / match.group(0)
                    if path not in service.path_deps:
                        service.path_deps.add(path)
                        LOG.info(
                            "Image %s depends on path %s", service.name, match.group(0)
                        )

    def mark_changed_dirty(self, changed_paths):
        """Find changed services and images that depend on them.

        Arguments:
            changed_paths (iterable(Path)): List of paths changed.
        """
        # find first order dependencies
        for path in changed_paths:
            for service in self.values():
                # shortcut if service is already marked dirty
                if service.dirty:
                    continue
                # check for path dependencies
                if path in service.path_deps:
                    LOG.info(
                        "%s is dirty because path %s is changed", service.name, path
                    )
                    service.dirty = True
                    continue

        # propagate dirty bit to image dependencies
        while True:
            any_changed = False
            for service in self.values():
                dirty_dep = next(
                    (dep for dep in service.service_deps if self[dep].dirty), None
                )
                if not service.dirty and dirty_dep is not None:
                    LOG.info(
                        "%s is dirty because image %s is dirty", service.name, dirty_dep
                    )
                    service.dirty = True
                    any_changed = True
            if not any_changed:
                break

# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Orion service definitions"""


import re
from abc import ABC, abstractmethod
from itertools import chain
from logging import getLogger
from pathlib import Path
from platform import machine
from re import Pattern
from typing import Any, Dict, Iterable, List, Optional, Set, Union

from dockerfile_parse import DockerfileParser
from yaml import safe_load as yaml_load

from .git import GitRepo

LOG = getLogger(__name__)


def file_glob(
    repo: GitRepo, path: Path, pattern: str = "**/*", relative: bool = False
) -> Iterable[Path]:
    """Run Path.glob for a given pattern, with filters applied.
    Only files are yielded, not directories. Any file that looks like
    it is in a test folder hierarchy (`tests`) will be skipped.

    Arguments:
        repo: Git repository in which to search.
        path: Root for the glob expression.
        pattern: Glob expression.
        relative: Result will be relative to `path`.

    Yields:
        Result paths.
    """
    assert repo.path is not None
    git_files = [
        repo.path / p
        for p in repo.git(
            "ls-files", "--", str(path.relative_to(repo.path))
        ).splitlines()
    ]
    for result in path.glob(pattern):
        if not result.is_file() or result not in git_files:
            continue
        relative_result = result.relative_to(path)
        if "tests" not in relative_result.parts:
            if relative:
                yield relative_result
            else:
                yield result


class ServiceTest(ABC):
    """Orion service test

    Tests that operate either on the service definition, or the resulting image.

    Attributes:
        name: Test name
    """

    FIELDS = frozenset(("name", "type"))

    def __init__(self, name: str) -> None:
        """Initialize a ServiceTest instance.

        Arguments:
            name: Test name
        """
        self.name = name

    @abstractmethod
    def update_task(
        self,
        task: Dict[str, Any],
        clone_url: str,
        fetch_ref: str,
        commit: str,
        service_rel_path: str,
    ) -> None:
        """Update a task definition to run the tests.

        Arguments:
            task: Task definition to update.
            clone_url: Git clone URL
            fetch_ref: Git fetch reference
            commit: Git revision
            service_rel_path: Relative path to service definition from repo root
        """

    @classmethod
    def check_fields(cls, defn: Dict[str, str], check_unknown: bool = True) -> None:
        """Check a service test definition fields.

        Arguments:
            defn: Test definition from service.yaml
            check_unknown: Check for unknown fields as well as missing.
        """
        LOG.debug("got fields %r", cls.FIELDS)
        given_fields = frozenset(defn)
        missing = list(cls.FIELDS - given_fields)
        if missing:
            raise RuntimeError(f"Missing test fields: '{missing!r}'")
        if check_unknown:
            extra = list(given_fields - cls.FIELDS)
            if extra:
                raise RuntimeError(f"Unknown test fields: '{extra!r}'")

    @staticmethod
    def from_defn(defn: Dict[str, str]) -> "ToxServiceTest":
        """Load a service test from the service.yaml metadata test subsection.

        Arguments:
            defn: Test definition from service.yaml
        """
        ServiceTest.check_fields(defn, check_unknown=False)
        if defn["type"] == "tox":
            ToxServiceTest.check_fields(defn)
            return ToxServiceTest(defn["name"], defn["image"], defn["toxenv"])
        raise RuntimeError(f"Unrecognized test 'type': {defn['type']!r}")


class ToxServiceTest(ServiceTest):
    """Orion service test -- tox

    Run Tox for python unit-tests in a service definition.

    Attributes:
        name: Test name
        image: Docker image to use for test execution. This can be either a
               registry name (eg. `python:3.8`) or a service name defined in Orion
               (eg. `ci-py-38`). For services, either the task built in this
               decision tree, or the latest indexed-image will be used.
        toxenv: tox env to run
    """

    FIELDS = frozenset({"image", "toxenv"} | ServiceTest.FIELDS)

    def __init__(self, name: str, image: str, toxenv: str) -> None:
        """
        Arguments:
            name: Test name
            image: Docker image to use for test execution (see class doc)
            toxenv: tox env to run
        """
        super().__init__(name)
        self.image = image
        self.toxenv = toxenv

    def update_task(
        self,
        task: Dict[str, Any],
        clone_url: str,
        fetch_ref: str,
        commit: str,
        service_rel_path: str,
    ) -> None:
        """Update a task definition to run the tests.

        Arguments:
            task: Task definition to update.
            clone_url: Git clone URL
            fetch_ref: Git reference to fetch
            commit: Git revision
            service_rel_path: Relative path to service definition from repo root
        """
        task["payload"]["command"] = [
            "/bin/bash",
            "--login",
            "-x",
            "-c",
            'retry () { for _ in {1..9}; do "$@" && return || sleep 30; done; "$@"; } '
            "&& "
            "git init repo && "
            "cd repo && "
            f"git remote add origin '{clone_url}' && "
            f"retry git fetch -q --depth=10 origin '{fetch_ref}' && "
            f"git -c advice.detachedHead=false checkout '{commit}' && "
            f"cd '{service_rel_path}' && "
            f"tox -e '{self.toxenv}'",
        ]


class Service:
    """Orion service (Docker image)

    Attributes:
        dockerfile: Path to the Dockerfile
        context: build context
        name: Image name (Docker tag)
        service_deps: Names of images that this one depends on.
        path_deps: Paths that this image depends on.
        recipe_deps: Names of recipes that this service depends on.
        weak_deps: Names of images that should trigger a rebuild of this one
                              but are not build deps.
        dirty: Whether or not this image needs to be rebuilt
        tests: Tests to run against this service
        root: Path where service is defined
    """

    def __init__(
        self,
        dockerfile: Optional[Path],
        context: Path,
        name: str,
        tests: List[ServiceTest],
        root: Path,
    ) -> None:
        """Initialize a Service instance.

        Arguments:
            dockerfile: Path to the Dockerfile
            context: build context
            name: Image name (Docker tag)
            tests: Tests to run against this service
            root: Path where service is defined
        """
        self.dockerfile = dockerfile
        self.context = context
        self.name = name
        self.service_deps: Set[str] = set()
        self.path_deps: Set[Path] = set()
        self.recipe_deps: Set[str] = set()
        self.weak_deps: Set[str] = set()
        self.dirty = False
        self.tests = tests
        self.root = root

    @classmethod
    def from_metadata_yaml(cls, metadata_path: Path, context: Path) -> "Service":
        """Create a Service instance from a service.yaml metadata path.

        Arguments:
            metadata_path: Path to a service.yaml file.
            context: The context from which this service is built.

        Returns:
            A service instance.
        """
        metadata = yaml_load(metadata_path.read_text())
        name = metadata["name"]
        LOG.info("Loading %s from %s", name, metadata_path)
        tests: List[ServiceTest]
        if "tests" in metadata:
            tests = [ServiceTest.from_defn(defn) for defn in metadata["tests"]]
        else:
            tests = []
        if "type" in metadata:
            assert metadata["type"] in {"docker", "msys"}
        result: Service
        if metadata.get("type") == "msys":
            base = metadata["base"]
            assert (metadata_path.parent / "setup.sh").is_file()
            result = ServiceMsys(base, context, name, tests, metadata_path.parent)
        else:
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
            result = cls(dockerfile, context, name, tests, metadata_path.parent)
        result.service_deps |= set(metadata.get("force_deps", []))
        result.weak_deps |= set(metadata.get("force_dirty", []))
        return result


class ServiceMsys(Service):
    """Orion service (MSYS tar)

    Attributes:
        base: URL to MSYS base tar to use.
        context: build context
        name: Image name
        service_deps: Names of images that this one depends on.
        path_deps: Paths that this image depends on.
        recipe_deps: Names of recipes that this service depends on.
        dirty: Whether or not this image needs to be rebuilt
        tests: Tests to run against this service
        root: Path where service is defined
    """

    def __init__(
        self, base: str, context: Path, name: str, tests: List[ServiceTest], root: Path
    ) -> None:
        """Initialize a ServiceMsys instance.

        Arguments:
            base: URL to MSYS base tar to use.
            context: build context
            name: Image name
            tests: Tests to run against this service
            root: Path where service is defined
        """
        super().__init__(None, context, name, tests, root)
        self.base = base


class Recipe:
    """Installation recipe used by Orion Services.

    Attributes:
        file: Location of the recipe.
        service_deps: Set of services that this recipe depends on.
        path_deps: Paths that this recipe depends on.
        recipe_deps: Names of other recipes that this recipe depends on.
        weak_deps: Names of images that should trigger a rebuild of this one
                              but are not build deps.
        dirty: Whether or not this recipe needs tests run.
    """

    def __init__(self, file: Path) -> None:
        """Initialize a `Recipe` instance.

        Arguments:
            file: Location of the recipe
        """
        self.file = file
        self.service_deps: Set[str] = set()
        self.path_deps: Set[Path] = set([file])
        self.recipe_deps: Set[str] = set()
        self.weak_deps: Set[str] = set()
        self.dirty = False

    @property
    def name(self) -> str:
        return self.file.name


class Services(dict):
    """Collection of Orion Services.

    Attributes:
        services: Mapping of service name (`service.name`) to the `Service` instance.
        recipes: Mapping of recipe name (`recipe.sh`) to the `Recipe` instance.
        root: The root for loading services and watching recipe scripts.
    """

    def __init__(self, repo: GitRepo) -> None:
        """Initialize a `Services` instances.

        Arguments:
            The git repo to load services and recipe scripts from.
        """
        super().__init__()
        self.root = repo.path
        # scan files & recipes
        self.recipes: Dict[str, Recipe] = {}
        self._file_re = self._scan_files(repo)
        # scan the context recursively to find services
        assert self.root is not None
        for service_yaml in file_glob(repo, self.root, "**/service.yaml"):
            service = Service.from_metadata_yaml(service_yaml, self.root)
            assert service.name not in self
            assert service.dockerfile is not None
            service.path_deps |= {service_yaml, service.dockerfile}
            self[service.name] = service
        self._calculate_depends(repo)

    def _scan_files(self, repo: GitRepo) -> Pattern[str]:
        # make a list of all file paths
        file_strs = []
        assert self.root is not None
        for file in file_glob(repo, self.root, relative=True):
            file_strs.append(str(file))
            # recipes are usually called using only their basename
            if file.parts[0] == "recipes":
                file_strs.append(file.name)
                assert file.name not in self.recipes
                self.recipes[file.name] = Recipe(self.root / file)
            LOG.debug("found path: %s", file_strs[-1])
        return re.compile("|".join(re.escape(file) for file in file_strs))

    def _find_path_depends(self, obj: Union[Recipe, Service], text: str) -> None:
        """Search a file for path references.

        Arguments:
            obj: Object the file belongs to
            text: File contents to search
        """
        # search file for references to other files
        for initial_match in self._file_re.finditer(text):
            match = initial_match.group(0)
            assert self.root is not None
            path = self.root / match
            part0 = Path(match).parts[0]
            if (not path.is_file() and match in self.recipes) or part0 == "recipes":
                assert (
                    path.name in self.recipes
                ), f"{type(obj).__name__} {obj.name} depends on unknown recipe {match}"
                if path.name not in obj.recipe_deps:
                    obj.recipe_deps.add(path.name)
                    LOG.info(
                        "%s %s depends on Recipe %s",
                        type(obj).__name__,
                        obj.name,
                        path.name,
                    )
            elif path not in obj.path_deps and path.parent != self.root:
                obj.path_deps.add(path)
                LOG.info(
                    "%s %s depends on Path %s",
                    type(obj).__name__,
                    obj.name,
                    path.relative_to(self.root),
                )

    def _calculate_depends(self, repo: GitRepo) -> None:
        """Go through each service and try to determine what dependencies it has.

        There are four types of dependencies:
        - service: The base image used for the dockerfile (only for `mozillasecurity/`)
        - paths: Files in the same root that are used by the image.
        - forced: Use `/force-deps=service` in a recipe or "force_deps:[]" in
                  service.yaml to force a dependency on another service.
        - weak: Use `/force-dirty=service` in a recipe or "force_dirty:[]" in
                service.yaml to force rebuild of this service if another changes, but
                not a build dependency.

        Arguments:
            The git repo to load services and recipe scripts from.
        """
        for recipe in self.recipes.values():
            try:
                recipe_text = recipe.file.read_text()
            except UnicodeError:
                continue

            # find force-deps in recipe
            for match in re.finditer(
                r"/force-(deps|dirty)=([A-Za-z0-9_.,-]+)", recipe_text
            ):
                for svc in match.group(2).split(","):
                    msg = (
                        "forces unknown dep"
                        if match.group(1) == "deps"
                        else "dirtied by unknown"
                    )
                    assert svc in self, f"Recipe {recipe.name} {msg}: {svc}"
                    if match.group(1) == "deps":
                        recipe.service_deps.add(svc)
                    else:
                        recipe.weak_deps.add(svc)

            # search file for references to other files
            self._find_path_depends(recipe, recipe_text)

        for service in self.values():
            # check force_deps
            # if a dep already exists, it had to come from force_deps in service.yaml
            for dep in service.service_deps:
                assert dep in self, f"Service {service.name} forces unknown dep: {dep}"
                LOG.info("Service %s depends on service %s (forced)", service.name, dep)
            # check force_dirty
            for dep in service.weak_deps:
                assert dep in self, f"Service {service.name} dirtied by unknown: {dep}"
                LOG.info(
                    "Service %s is dirty with service %s (forced)", service.name, dep
                )

            if isinstance(service, ServiceMsys):
                search_root = service.root
            else:
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
                    LOG.info(
                        "Service %s depends on Service %s", service.name, baseimage
                    )
                search_root = service.dockerfile.parent

            # scan service for references to files
            for entry in file_glob(repo, search_root):
                # add a direct dependency on any file in the service folder
                if entry not in service.path_deps:
                    service.path_deps.add(entry)
                    assert self.root is not None
                    LOG.info(
                        "Service %s depends on Path %s",
                        service.name,
                        entry.relative_to(self.root),
                    )

                try:
                    entry_text = entry.read_text()
                except UnicodeError:
                    continue

                # search file for references to other files
                self._find_path_depends(service, entry_text)

        def _adjacent(obj: Service) -> Iterable[Union[Recipe, Service]]:
            for rec in obj.recipe_deps:
                yield self.recipes[rec]
            for svc in obj.service_deps:
                yield self[svc]
            # include service test images
            if hasattr(obj, "tests"):
                for test in obj.tests:
                    if hasattr(test, "image"):
                        assert isinstance(test, ToxServiceTest)
                        if test.image in self:
                            yield self[test.image]

        # check that there are no cycles in the dependency graph
        for start in chain(self.values(), self.recipes.values()):
            stk: List[Optional[Iterable[Union[Recipe, Service]]]] = [_adjacent(start)]
            bkt = [start]
            while stk:
                if stk[-1] is None:
                    bkt.pop()
                    stk.pop()
                    continue
                here = next(stk[-1], None)
                if here is None:
                    stk.pop()
                else:
                    if here in bkt:
                        bkt.append(here)
                        fmt_bkt = ", ".join(
                            f"{type(obj).__name__} {obj.name}" for obj in bkt
                        )
                        raise RuntimeError(f"Dependency cycle detected: [{fmt_bkt}]")
                    bkt.append(here)
                    stk.append(None)  # sentinel
                    stk.append(_adjacent(here))

    def mark_changed_dirty(self, changed_paths: Iterable[Path]) -> None:
        """Find changed services and images that depend on them.

        Arguments:
            List of paths changed.
        """
        stk = []
        # find first order dependencies
        for path in changed_paths:
            for here in chain(self.values(), self.recipes.values()):
                # shortcut if already marked dirty
                if here.dirty:
                    continue
                # check for path dependencies
                if path in here.path_deps:
                    assert self.root is not None
                    LOG.warning(
                        "%s %s is dirty because Path %s is changed",
                        type(here).__name__,
                        here.name,
                        path.relative_to(self.root),
                    )
                    here.dirty = True
                    stk.append(here)
                    continue

        # propagate dirty bit
        while stk:
            here = stk.pop()
            for tgt in chain(self.values(), self.recipes.values()):
                if not tgt.dirty and (
                    (isinstance(here, Recipe) and here.name in tgt.recipe_deps)
                    or (
                        isinstance(here, Service)
                        and here.name in tgt.weak_deps | tgt.service_deps
                    )
                ):
                    tgt.dirty = True
                    LOG.warning(
                        "%s %s is dirty because %s %s is dirty",
                        type(tgt).__name__,
                        tgt.name,
                        type(here).__name__,
                        here.name,
                    )
                    stk.append(tgt)

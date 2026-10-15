# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Orion service definitions"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from itertools import chain
from logging import getLogger
from pathlib import Path
from re import Pattern
from typing import Any

from dockerfile_parse import DockerfileParser
from yaml import safe_load as yaml_load

from .git import GitRepo

LOG = getLogger(__name__)


def file_glob(
    repo: GitRepo,
    path: Path,
    pattern: str = "**/*",
    relative: bool = False,
    include_tests: bool = False,
) -> Iterator[Path]:
    """Run Path.glob for a given pattern, with filters applied.
    Only files are yielded, not directories. Files in test folder hierarchies
    (`tests`) are skipped unless they are needed for dependency tracking.

    Arguments:
        repo: Git repository in which to search.
        path: Root for the glob expression.
        pattern: Glob expression.
        relative: Result will be relative to `path`.
        include_tests: Include files below directories named `tests`.

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
        if include_tests or "tests" not in relative_result.parts:
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
        task: dict[str, Any],
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
    def check_fields(cls, defn: dict[str, str], check_unknown: bool = True) -> None:
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
    def from_defn(defn: dict[str, str]) -> ToxServiceTest:
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
        task: dict[str, Any],
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
        weak_deps: Names of images that should trigger a rebuild of this one but are not
                   build deps.
        dirty: Whether or not this image needs to be rebuilt
        tests: Tests to run against this service
        root: Path where service is defined
        archs: List of Linux architectures (e.g. amd64, arm64)
    """

    def __init__(
        self,
        dockerfile: Path | None,
        context: Path,
        name: str,
        tests: list[ServiceTest],
        root: Path,
        archs: list[str] | None = None,
    ) -> None:
        """Initialize a Service instance.

        Arguments:
            dockerfile: Path to the Dockerfile
            context: build context
            name: Image name (Docker tag)
            tests: Tests to run against this service
            root: Path where service is defined
            archs: List of Linux architectures (e.g. amd64, arm64)
        """
        self.dockerfile = dockerfile
        self.context = context
        self.name = name
        self.service_deps: set[str] = set()
        self.path_deps: set[Path] = set()
        self.recipe_deps: set[str] = set()
        self.weak_deps: set[str] = set()
        self.dirty = False
        self.tests = tests
        self.root = root
        self.archs = archs or ["amd64"]

    @classmethod
    def from_metadata_yaml(cls, metadata_path: Path, context: Path) -> Service:
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
        tests: list[ServiceTest]
        if "tests" in metadata:
            tests = [ServiceTest.from_defn(defn) for defn in metadata["tests"]]
        else:
            tests = []
        if "type" in metadata:
            assert metadata["type"] in {"docker", "msys", "homebrew", "test"}
        result: Service
        if metadata.get("type") == "msys":
            base = metadata["base"]
            assert (metadata_path.parent / "setup.sh").is_file()
            result = ServiceMsys(base, context, name, tests, metadata_path.parent)
        elif metadata.get("type") == "homebrew":
            base = metadata["base"]
            assert (metadata_path.parent / "setup.sh").is_file()
            result = ServiceHomebrew(base, context, name, tests, metadata_path.parent)
        elif metadata.get("type") == "test":
            result = ServiceTestOnly(context, name, tests, metadata_path.parent)
        else:
            dockerfile = metadata_path.parent / "Dockerfile"
            assert dockerfile.is_file()
            archs = metadata["arch"] if "arch" in metadata else ["amd64"]
            result = cls(dockerfile, context, name, tests, metadata_path.parent, archs)
        result.service_deps |= set(metadata.get("force_deps", []))
        result.weak_deps |= set(metadata.get("force_dirty", []))
        return result


class ServiceHomebrew(Service):
    """Orion service (Homebrew tar)

    Attributes:
        base (str): URL to Homebrew base tar to use.
        context (Path): build context
        name (str): Image name
        service_deps (set(str)): Names of images that this one depends on.
        path_deps (set(Path)): Paths that this image depends on.
        recipe_deps (set(str)): Names of recipes that this service depends on.
        dirty (bool): Whether or not this image needs to be rebuilt
        tests (list[ServiceTest]): Tests to run against this service
        root (Path): Path where service is defined
    """

    def __init__(self, base, context, name, tests, root):
        """Initialize a ServiceHomebrew instance.

        Arguments:
            base (str): URL to Homebrew base tar to use.
            context (Path): build context
            name (str): Image name
            tests (list[ServiceTest]): Tests to run against this service
            root (Path): Path where service is defined
        """
        super().__init__(None, context, name, tests, root)
        self.base = base


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
        self, base: str, context: Path, name: str, tests: list[ServiceTest], root: Path
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


class ServiceTestOnly(Service):
    """Orion service (no-op)

    Attributes:
        context (Path): build context
        name (str): Image name
        service_deps (set(str)): Names of images that this one depends on.
        path_deps (set(Path)): Paths that this image depends on.
        recipe_deps (set(str)): Names of recipes that this service depends on.
        dirty (bool): Whether or not this image needs to be rebuilt
        tests (list[ServiceTest]): Tests to run against this service
        root (Path): Path where service is defined
    """

    def __init__(self, context, name, tests, root):
        """Initialize a ServiceTestOnly instance.

        Arguments:
            context (Path): build context
            name (str): Image name
            tests (list[ServiceTest]): Tests to run against this service
            root (Path): Path where service is defined
        """
        super().__init__(None, context, name, tests, root)


class Recipe:
    """Installation recipe used by Orion Services.

    Attributes:
        file: Location of the recipe.
        service_deps: Set of services that this recipe depends on.
        path_deps: Paths that this recipe depends on.
        recipe_deps: Names of other recipes that this recipe depends on.
        weak_deps: Names of images that should trigger a rebuild of this one but are not
                   build deps.
        dirty: Whether or not this recipe needs tests run.
    """

    def __init__(self, file: Path) -> None:
        """Initialize a `Recipe` instance.

        Arguments:
            file: Location of the recipe
        """
        self.file = file
        self.service_deps: set[str] = set()
        self.path_deps: set[Path] = {file}
        self.recipe_deps: set[str] = set()
        self.weak_deps: set[str] = set()
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
        self.recipes: dict[str, Recipe] = {}
        self._file_re = self._scan_files(repo)
        # scan the context recursively to find services
        assert self.root is not None
        for service_yaml in file_glob(repo, self.root, "**/service.yaml"):
            service = Service.from_metadata_yaml(service_yaml, self.root)
            assert service.name not in self, f"{service_yaml} missing name"
            service.path_deps.add(service_yaml)
            if service.dockerfile is not None:
                service.path_deps.add(service.dockerfile)
            self[service.name] = service
        self._calculate_depends(repo)

    def _scan_files(self, repo: GitRepo) -> Pattern[str]:
        # make a list of all file paths
        file_strs = []
        assert self.root is not None
        for file in file_glob(repo, self.root, relative=True, include_tests=True):
            file_strs.append(str(file))
            # recipes are usually called using only their basename
            if file.parts[0] == "recipes" and "tests" not in file.parts[1:]:
                file_strs.append(file.name)
                assert file.name not in self.recipes
                self.recipes[file.name] = Recipe(self.root / file)
            LOG.debug("found path: %s", file_strs[-1])
        return re.compile("|".join(re.escape(file) for file in file_strs))

    def _find_path_depends(self, obj: Recipe | Service, text: str) -> None:
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
            recipe_reference = (not path.is_file() and match in self.recipes) or (
                part0 == "recipes" and path.name in self.recipes
            )
            if recipe_reference:
                if path.name not in obj.recipe_deps:
                    obj.recipe_deps.add(path.name)
                    LOG.info(
                        "%s %s depends on Recipe %s",
                        type(obj).__name__,
                        obj.name,
                        path.name,
                    )
            elif (
                path.exists()
                and part0 == "recipes"
                and "tests" in Path(match).parts[1:]
                and path not in obj.path_deps
            ):
                obj.path_deps.add(path)
                LOG.info(
                    "%s %s depends on Path %s",
                    type(obj).__name__,
                    obj.name,
                    path.relative_to(self.root),
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

            if isinstance(service, (ServiceTestOnly, ServiceMsys, ServiceHomebrew)):
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
            for entry in file_glob(repo, search_root, include_tests=True):
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

        def _adjacent(obj: Recipe | Service) -> Iterator[Recipe | Service]:
            for rec in obj.recipe_deps:
                yield self.recipes[rec]
            for svc in obj.service_deps:
                yield self[svc]
            # include service test images
            if hasattr(obj, "tests"):
                assert isinstance(obj, Service)
                for test in obj.tests:
                    if hasattr(test, "image"):
                        assert isinstance(test, ToxServiceTest)
                        if test.image in self:
                            yield self[test.image]

        # check that there are no cycles in the dependency graph
        for start in chain(self.values(), self.recipes.values()):
            stk: list[Iterator[Recipe | Service] | None] = [_adjacent(start)]
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

    def mark_changed_dirty(
        self,
        changed_paths: Iterable[Path],
        previous_services: Services | None = None,
    ) -> None:
        """Find changed services and images that depend on them.

        Arguments:
            List of paths changed.
        """
        changed_paths = list(changed_paths)
        stk = []
        assert self.root is not None
        if previous_services is not None:
            assert previous_services.root is not None
            previous_paths = [
                previous_services.root
                / (path.relative_to(self.root) if path.is_absolute() else path)
                for path in changed_paths
            ]
            previous_services.mark_changed_dirty(previous_paths)
            for name, old_service in previous_services.items():
                if old_service.dirty and name in self:
                    self[name].dirty = True
                    stk.append(self[name])
            for name, old_recipe in previous_services.recipes.items():
                if old_recipe.dirty and name in self.recipes:
                    self.recipes[name].dirty = True
                    stk.append(self.recipes[name])
        # find first order dependencies
        for path in changed_paths:
            absolute_path = path if path.is_absolute() else self.root / path
            for here in chain(self.values(), self.recipes.values()):
                # shortcut if already marked dirty
                if here.dirty:
                    continue
                # check for path dependencies
                # A deleted file can no longer appear in path_deps. Match it to
                # the owning service/recipe directory as a conservative fallback.
                deleted_from_service = (
                    isinstance(here, Service)
                    and not absolute_path.exists()
                    and here.root in absolute_path.parents
                )
                if absolute_path in here.path_deps or deleted_from_service:
                    LOG.warning(
                        "%s %s is dirty because Path %s is changed",
                        type(here).__name__,
                        here.name,
                        absolute_path.relative_to(self.root),
                    )
                    here.dirty = True
                    stk.append(here)
                    continue
        self.propagate_dirty(stk)

    def force_dirty(self, service_names: Iterable[str]) -> None:
        """Dirty selected services and propagate through all dependency edges."""
        selected = []
        for name in service_names:
            service = self[name]
            if not service.dirty:
                service.dirty = True
            selected.append(service)
        self.propagate_dirty(selected)

    def propagate_dirty(self, dirty_svcs: Iterable[Service]) -> None:
        stk = list(dirty_svcs)
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

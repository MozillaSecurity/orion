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

from dockerfile_parse import DockerfileParser
from yaml import safe_load as yaml_load

LOG = getLogger(__name__)


def file_glob(repo, path, pattern="**/*", relative=False):
    """Run Path.glob for a given pattern, with filters applied.
    Only files are yielded, not directories. Any file that looks like
    it is in a test folder hierarchy (`tests`) will be skipped.

    Arguments:
        repo (GitRepo): Git repository in which to search.
        path (Path): Root for the glob expression.
        pattern (str): Glob expression.
        relative (bool): Result will be relative to `path`.

    Yields:
        Path: Result paths.
    """
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
        name (str): Test name
    """

    FIELDS = frozenset(("name", "type"))

    def __init__(self, name):
        """Initialize a ServiceTest instance.

        Arguments:
            name (str): Test name
        """
        self.name = name

    @abstractmethod
    def update_task(self, task, clone_url, fetch_ref, commit, service_rel_path):
        """Update a task definition to run the tests.

        Arguments:
            task (dict): Task definition to update.
            clone_url (str): Git clone URL
            fetch_ref (str): Git fetch reference
            commit (str): Git revision
            service_rel_path (str): Relative path to service definition from repo root
        """

    @classmethod
    def check_fields(cls, defn, check_unknown=True):
        """Check a service test definition fields.

        Arguments:
            defn (dict): Test definition from service.yaml
            check_unknown (bool): Check for unknown fields as well as missing.
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
    def from_defn(defn):
        """Load a service test from the service.yaml metadata test subsection.

        Arguments:
            defn (dict): Test definition from service.yaml
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
        name (str): Test name
        image (str): Docker image to use for test execution. This can be either a
                     registry name (eg. `python:3.8`) or a service name defined in Orion
                     (eg. `ci-py-38`). For services, either the task built in this
                     decision tree, or the latest indexed-image will be used.
        toxenv (str): tox env to run
    """

    FIELDS = frozenset({"image", "toxenv"} | ServiceTest.FIELDS)

    def __init__(self, name, image, toxenv):
        """
        Arguments:
            name (str): Test name
            image (str): Docker image to use for test execution (see class doc)
            toxenv (str): tox env to run
        """
        super().__init__(name)
        self.image = image
        self.toxenv = toxenv

    def update_task(self, task, clone_url, fetch_ref, commit, service_rel_path):
        """Update a task definition to run the tests.

        Arguments:
            task (dict): Task definition to update.
            clone_url (str): Git clone URL
            fetch_ref (str): Git reference to fetch
            commit (str): Git revision
            service_rel_path (str): Relative path to service definition from repo root
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
        dockerfile (Path): Path to the Dockerfile
        context (Path): build context
        name (str): Image name (Docker tag)
        service_deps (set(str)): Names of images that this one depends on.
        path_deps (set(Path)): Paths that this image depends on.
        recipe_deps (set(str)): Names of recipes that this service depends on.
        dirty (bool): Whether or not this image needs to be rebuilt
        tests (list[ServiceTest]): Tests to run against this service
        root (Path): Path where service is defined
    """

    def __init__(self, dockerfile, context, name, tests, root):
        """Initialize a Service instance.

        Arguments:
            dockerfile (Path): Path to the Dockerfile
            context (Path): build context
            name (str): Image name (Docker tag)
            tests (list[ServiceTest]): Tests to run against this service
            root (Path): Path where service is defined
        """
        self.dockerfile = dockerfile
        self.context = context
        self.name = name
        self.service_deps = set()
        self.path_deps = set()
        self.recipe_deps = set()
        self.dirty = False
        self.tests = tests
        self.root = root

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
        if "tests" in metadata:
            tests = [ServiceTest.from_defn(defn) for defn in metadata["tests"]]
        else:
            tests = []
        result = cls(dockerfile, context, name, tests, metadata_path.parent)
        result.service_deps |= set(metadata.get("force_deps", []))
        return result


class Recipe:
    """Installation recipe used by Orion Services.

    Attributes:
        file (Path): Location of the recipe.
        service_deps (set(str)): Set of services that this recipe depends on.
        path_deps (set(Path)): Paths that this recipe depends on.
        recipe_deps (set(str)): Names of other recipes that this recipe depends on.
        dirty (bool): Whether or not this recipe needs tests run.
    """

    def __init__(self, file):
        """Initialize a `Recipe` instance.

        Arguments:
            file (Path): Location of the recipe
        """
        self.file = file
        self.service_deps = set()
        self.path_deps = set([file])
        self.recipe_deps = set()
        self.dirty = False

    @property
    def name(self):
        return self.file.name


class Services(dict):
    """Collection of Orion Services.

    Attributes:
        services (dict(str -> Service)): Mapping of service name (`service.name`) to
                                         the `Service` instance.
        recipes (dict(str -> Recipe)): Mapping of recipe name (`recipe.sh`) to the
                                       `Recipe` instance.
        root (Path): The root for loading services and watching recipe scripts.
    """

    def __init__(self, repo):
        """Initialize a `Services` instances.

        Arguments:
            repo (GitRepo): The git repo to load services and recipe scripts from.
        """
        super().__init__()
        self.root = repo.path
        # scan files & recipes
        self.recipes = {}
        self._file_re = self._scan_files(repo)
        # scan the context recursively to find services
        for service_yaml in file_glob(repo, self.root, "**/service.yaml"):
            service = Service.from_metadata_yaml(service_yaml, self.root)
            assert service.name not in self
            service.path_deps |= {service_yaml, service.dockerfile}
            self[service.name] = service
        self._calculate_depends(repo)

    def _scan_files(self, repo):
        # make a list of all file paths
        file_strs = []
        for file in file_glob(repo, self.root, relative=True):
            file_strs.append(str(file))
            # recipes are usually called using only their basename
            if file.parts[0] == "recipes":
                file_strs.append(file.name)
                assert file.name not in self.recipes
                self.recipes[file.name] = Recipe(self.root / file)
            LOG.debug("found path: %s", file_strs[-1])
        return re.compile("|".join(re.escape(file) for file in file_strs))

    def _find_path_depends(self, obj, text):
        """Search a file for path references.

        Arguments:
            obj (Recipe/Service): Object the file belongs to
            text (str): File contents to search

        Returns:
            None
        """
        # search file for references to other files
        for match in self._file_re.finditer(text):
            match = match.group(0)
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
            elif path not in obj.path_deps:
                obj.path_deps.add(path)
                LOG.info(
                    "%s %s depends on path %s",
                    type(obj).__name__,
                    obj.name,
                    path.relative_to(self.root),
                )

    def _calculate_depends(self, repo):
        """Go through each service and try to determine what dependencies it has.

        There are three types of dependencies:
        - service: The base image used for the dockerfile (only for `mozillasecurity/`)
        - paths: Files in the same root that are used by the image.
        - forced: Use `/force-deps=service` in a recipe or "force_deps:[]" in
                  service.yaml to force a dependency on another service.

        Arguments:
            repo (GitRepo): The git repo to load services and recipe scripts from.

        Returns:
            None
        """
        for recipe in self.recipes.values():
            try:
                recipe_text = recipe.file.read_text()
            except UnicodeError:
                continue

            # find force-deps in recipe
            for match in re.finditer(r"/force-deps=([A-Za-z0-9_.,-]+)", recipe_text):
                for svc in match.group(1).split(","):
                    assert (
                        svc in self
                    ), f"Recipe {recipe.name} forces unknown dep: {svc}"
                    recipe.service_deps.add(svc)

            # search file for references to other files
            self._find_path_depends(recipe, recipe_text)

        for service in self.values():
            # check force_deps
            # if a dep already exists, it had to come from force_deps in service.yaml
            for dep in service.service_deps:
                assert dep in self, f"Service {service.name} forces unknown dep: {dep}"
                LOG.info("Service %s depends on service %s (forced)", service.name, dep)

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
                LOG.info("Service %s depends on Service %s", service.name, baseimage)

            # scan service for references to files
            for entry in file_glob(repo, service.dockerfile.parent):
                # add a direct dependency on any file in the service folder
                if entry not in service.path_deps:
                    service.path_deps.add(entry)
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

        def _adjacent(obj):
            for rec in obj.recipe_deps:
                yield self.recipes[rec]
            for svc in obj.service_deps:
                yield self[svc]

        # check that there are no cycles in the dependency graph
        for start in chain(self.values(), self.recipes.values()):
            stk = [_adjacent(start)]
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

    def mark_changed_dirty(self, changed_paths):
        """Find changed services and images that depend on them.

        Arguments:
            changed_paths (iterable(Path)): List of paths changed.
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
                    or (isinstance(here, Service) and here.name in tgt.service_deps)
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

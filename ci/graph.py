"""Service and recipe dependency graph for Orion image builds."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class GraphError(ValueError):
    """Invalid or inconsistent service metadata or dependencies."""


@dataclass
class Node:
    name: str
    kind: str
    context: str
    service_root: str = "."
    dockerfile: str | None = None
    setup: str | None = None
    base: str | None = None
    archs: list[str] = field(default_factory=lambda: ["amd64"])
    dependencies: set[str] = field(default_factory=set)
    image_dependencies: set[str] = field(default_factory=set)
    weak_dependencies: set[str] = field(default_factory=set)
    configured_dependencies: set[str] = field(default_factory=set)
    configured_weak_dependencies: set[str] = field(default_factory=set)
    recipe_dependencies: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    tests: list[dict[str, Any]] = field(default_factory=list)
    dirty: bool = False

    def output(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "context": self.context,
            "dockerfile": self.dockerfile,
            "setup": self.setup,
            "base": self.base,
            "archs": sorted(self.archs),
            "dependencies": sorted(self.dependencies),
            "image_dependencies": sorted(self.image_dependencies),
            "dirty": self.dirty,
            "tests": self.tests,
        }


@dataclass
class Recipe:
    name: str
    path: str
    services: set[str] = field(default_factory=set)
    weak_services: set[str] = field(default_factory=set)
    recipes: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    dirty: bool = False


_FORCE = re.compile(r"/force-(deps|dirty)=([A-Za-z0-9_.,-]+)")


def _git_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return {
        p.decode()
        for p in result.stdout.split(b"\0")
        if p and (root / p.decode()).is_file()
    }


def _safe_read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text()
    except (OSError, UnicodeError):
        return ""


def _dockerfile_dependencies(text: str) -> tuple[list[str], set[str], set[str]]:
    """Return base references, copied paths, and COPY --from names."""
    stages: set[str] = set()
    bases: list[str] = []
    copies: set[str] = set()
    copy_from: set[str] = set()
    instructions: list[str] = []
    pending = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending += stripped[:-1] + " " if stripped.endswith("\\") else stripped
        if not stripped.endswith("\\"):
            instructions.append(pending)
            pending = ""
    if pending:
        instructions.append(pending)
    for instruction in instructions:
        keyword, _, args = instruction.partition(" ")
        if keyword.upper() == "FROM":
            tokens = shlex.split(args)
            tokens = [token for token in tokens if not token.startswith("--")]
            if not tokens:
                continue
            image = tokens[0]
            alias = (
                tokens[2] if len(tokens) >= 3 and tokens[1].upper() == "AS" else None
            )
            if (
                image.lower() not in stages
                and image.lower() != "scratch"
                and "$" not in image
            ):
                bases.append(image)
            if alias:
                stages.add(alias.lower())
            continue
        if keyword.upper() not in {"COPY", "ADD"}:
            continue
        try:
            tokens = (
                json.loads(args) if args.lstrip().startswith("[") else shlex.split(args)
            )
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(tokens, list):
            continue
        source_image = next(
            (
                str(token).split("=", 1)[1].strip("\"'")
                for token in tokens
                if str(token).startswith("--from=")
            ),
            None,
        )
        if source_image:
            if source_image.lower() not in stages:
                copy_from.add(source_image)
            continue
        operands = [str(token) for token in tokens if not str(token).startswith("--")]
        for source in operands[:-1]:
            if (
                source.startswith("http://")
                or source.startswith("https://")
                or source.startswith("$")
            ):
                continue
            copies.add(source.lstrip("/"))
    return bases, copies, copy_from


def _path_matches(path: str, reference: str) -> bool:
    """Match COPY paths including directories and globs against tracked paths."""
    if any(char in reference for char in "*?["):
        import fnmatch

        return fnmatch.fnmatch(path, reference)
    return path == reference or path.startswith(reference.rstrip("/") + "/")


class ServiceGraph:
    """Load service and recipe inputs and calculate dirtiness."""

    def __init__(self, root: Path, tracked: Iterable[str] | None = None):
        self.root = root.resolve()
        self.tracked = set(tracked if tracked is not None else _git_files(self.root))
        self.services: dict[str, Node] = {}
        self.recipes: dict[str, Recipe] = {}
        self._load()
        self._dependencies()
        self._validate()

    def _load(self) -> None:
        for rel in sorted(self.tracked):
            if (
                PurePosixPath(rel).name != "service.yaml"
                or "/tests/fixtures/" in f"/{rel}/"
                or not (self.root / rel).is_file()
            ):
                continue
            metadata = yaml.safe_load(_safe_read(self.root, rel)) or {}
            name = metadata.get("name")
            if not name:
                raise GraphError(f"{rel}: missing service name")
            if name in self.services:
                raise GraphError(f"duplicate service name: {name}")
            directory = str(PurePosixPath(rel).parent)
            kind = metadata.get("type", "docker")
            if kind not in {"docker", "msys", "homebrew", "test"}:
                raise GraphError(f"{rel}: unsupported service type {kind!r}")
            self.services[name] = Node(
                name=name,
                kind=kind,
                context=".",
                service_root="" if directory == "." else directory,
                dockerfile=f"{directory}/Dockerfile" if kind == "docker" else None,
                setup=f"{directory}/setup.sh" if kind in {"msys", "homebrew"} else None,
                base=metadata.get("base"),
                archs=list(metadata.get("arch", ["amd64"])),
                paths={rel},
                tests=list(metadata.get("tests", [])),
                configured_dependencies=set(metadata.get("force_deps", [])),
                configured_weak_dependencies=set(metadata.get("force_dirty", [])),
            )
            if kind == "test":
                self.services[name].paths.update(self._all_files_under(directory))
                if directory != ".":
                    self.services[name].paths.add(directory)
        for rel in sorted(self.tracked):
            if not rel.startswith("recipes/") or not rel.endswith(".sh"):
                continue
            name = PurePosixPath(rel).name
            if name in self.recipes:
                raise GraphError(f"duplicate recipe basename: {name}")
            self.recipes[name] = Recipe(name=name, path=rel, paths={rel})

    def _all_files_under(self, prefix: str) -> set[str]:
        if prefix in {".", ""}:
            return {path for path in self.tracked if "/" not in path}
        return {p for p in self.tracked if p.startswith(prefix.rstrip("/") + "/")}

    def _resolve_text_references(self, owner: Node | Recipe, text: str) -> None:
        for recipe in self.recipes.values():
            if recipe is not owner and (recipe.name in text or recipe.path in text):
                owner.recipes.add(recipe.name) if isinstance(
                    owner, Recipe
                ) else owner.recipe_dependencies.add(recipe.name)
        for path in self.tracked:
            if path.startswith("recipes/"):
                continue
            if path in text:
                owner.paths.add(path)

    def _dependencies(self) -> None:
        for recipe in self.recipes.values():
            text = _safe_read(self.root, recipe.path)
            for mode, names in _FORCE.findall(text):
                target = recipe.services if mode == "deps" else recipe.weak_services
                target.update(names.split(","))
            self._resolve_text_references(recipe, text)
            # Explicit recipe names are dependencies even when they occur in comments.
            recipe.recipes.update(
                name for name in self.recipes if name in text and name != recipe.name
            )

        for service in self.services.values():
            service.dependencies.update(service.configured_dependencies)
            service.weak_dependencies.update(service.configured_weak_dependencies)
            if service.service_root:
                service.paths.add(service.service_root)
            if service.kind == "docker" and service.dockerfile:
                text = _safe_read(self.root, service.dockerfile)
                # Everything in a service directory is an input to its image.
                service.paths.update(self._all_files_under(service.service_root))
                bases, copies, copy_from = _dockerfile_dependencies(text)
                for image in bases + sorted(copy_from):
                    dep = self._local_image(image)
                    if dep:
                        service.dependencies.add(dep)
                        service.image_dependencies.add(dep)
                    if service.base is None and image in bases:
                        service.base = image
                for source in copies:
                    # Keep unresolved/deleted inputs: a diff can still contain a
                    # deleted path, and it must dirty the image that copied it.
                    service.paths.add(source)
                    for path in self.tracked:
                        if _path_matches(path, source):
                            service.paths.add(path)
            elif service.setup:
                service.paths.update(self._all_files_under(service.service_root))

            # Match recipe/path references in every local build input, including
            # shell scripts sourced by Dockerfiles and setup scripts.
            for path in self._all_files_under(service.service_root):
                self._resolve_text_references(service, _safe_read(self.root, path))

            for recipe_name in service.recipe_dependencies:
                recipe = self.recipes[recipe_name]
                service.dependencies.update(recipe.services)
                service.weak_dependencies.update(recipe.weak_services)
            for test in service.tests:
                image = test.get("image")
                if image in self.services:
                    service.dependencies.add(image)

        # Recipe changes flow to their direct users; force-deps and force-dirty
        # also make the recipe dirty when the referenced image changes.
        for recipe in self.recipes.values():
            self._resolve_text_references(recipe, _safe_read(self.root, recipe.path))

    def _local_image(self, reference: str) -> str | None:
        if not reference.startswith("mozillasecurity/"):
            return None
        image = reference.rsplit("/", 1)[-1]
        image = image.split("@", 1)[0].split(":", 1)[0]
        return image if image in self.services else None

    def _validate(self) -> None:
        for node in [*self.services.values(), *self.recipes.values()]:
            refs = (
                node.dependencies | node.weak_dependencies
                if isinstance(node, Node)
                else node.services | node.weak_services
            )
            unknown = refs - self.services.keys()
            if unknown:
                names = ", ".join(sorted(unknown))
                raise GraphError(f"{node.name} references unknown service(s): {names}")
            recipes = (
                node.recipe_dependencies if isinstance(node, Node) else node.recipes
            )
            unknown_recipes = recipes - self.recipes.keys()
            if unknown_recipes:
                names = ", ".join(sorted(unknown_recipes))
                raise GraphError(f"{node.name} references unknown recipe(s): {names}")
        state: set[str] = set()
        done: set[str] = set()

        def adjacent(key: str) -> set[str]:
            kind, name = key.split(":", 1)
            if kind == "service":
                node = self.services[name]
                return {f"service:{dep}" for dep in node.dependencies} | {
                    f"recipe:{dep}" for dep in node.recipe_dependencies
                }
            node = self.recipes[name]
            return {f"service:{dep}" for dep in node.services} | {
                f"recipe:{dep}" for dep in node.recipes
            }

        def visit(key: str, stack: list[str]) -> None:
            if key in state:
                raise GraphError("dependency cycle: " + " -> ".join([*stack, key]))
            if key in done:
                return
            state.add(key)
            for dep in sorted(adjacent(key)):
                visit(dep, [*stack, key])
            state.remove(key)
            done.add(key)

        for key in sorted(
            [f"service:{name}" for name in self.services]
            + [f"recipe:{name}" for name in self.recipes]
        ):
            visit(key, [])

    def mark_dirty(self, changed_paths: Iterable[str]) -> list[str]:
        changed = set(changed_paths)
        for node in [*self.services.values(), *self.recipes.values()]:
            if any(
                _path_matches(changed_path, dependency)
                for changed_path in changed
                for dependency in node.paths
            ):
                node.dirty = True
        if changed & {
            "services/test-recipes/launch.sh",
            "services/test-recipes/Dockerfile",
        }:
            for recipe in self.recipes.values():
                recipe.dirty = True
        for path in changed:
            prefix = "services/test-recipes/Dockerfile-"
            if path.startswith(prefix):
                name = PurePosixPath(path).name.removeprefix("Dockerfile-") + ".sh"
                if name in self.recipes:
                    self.recipes[name].dirty = True
        deleted_recipes = {
            PurePosixPath(path).name
            for path in changed
            if path.startswith("recipes/") and path.endswith(".sh")
        }
        if deleted_recipes:
            for recipe in self.recipes.values():
                text = _safe_read(self.root, recipe.path)
                if any(name in text for name in deleted_recipes):
                    recipe.dirty = True
            for service in self.services.values():
                source = service.dockerfile or service.setup
                text = _safe_read(self.root, source) if source else ""
                if any(name in text for name in deleted_recipes):
                    service.dirty = True
        changed_nodes = True
        while changed_nodes:
            changed_nodes = False
            dirty_services = {n.name for n in self.services.values() if n.dirty}
            dirty_recipes = {n.name for n in self.recipes.values() if n.dirty}
            for node in self.services.values():
                if not node.dirty and (
                    (node.dependencies | node.weak_dependencies) & dirty_services
                    or node.recipe_dependencies & dirty_recipes
                ):
                    node.dirty = True
                    changed_nodes = True
            for recipe in self.recipes.values():
                if not recipe.dirty and (
                    (recipe.services | recipe.weak_services) & dirty_services
                    or recipe.recipes & dirty_recipes
                ):
                    recipe.dirty = True
                    changed_nodes = True
        return sorted(name for name, node in self.services.items() if node.dirty)

    def plan(self, changed_paths: Iterable[str]) -> dict[str, Any]:
        dirty = self.mark_dirty(changed_paths)
        matrix = []
        for name in dirty:
            node = self.services[name]
            for test in node.tests:
                matrix.append(
                    {
                        "service": name,
                        "path": test.get(
                            "path",
                            str(
                                PurePosixPath(node.service_root)
                                if node.service_root
                                else PurePosixPath(".")
                            ),
                        ),
                        "python": test.get("python"),
                        "toxenv": test.get("toxenv"),
                        "name": test.get("name", f"{name} tests"),
                    }
                )
        return {
            "services": {
                name: node.output() for name, node in sorted(self.services.items())
            },
            "dirty": dirty,
            "recipes": sorted(
                name for name, recipe in self.recipes.items() if recipe.dirty
            ),
            "test_matrix": matrix,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Orion service dependencies")
    parser.add_argument("repo", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="validate and exit")
    args = parser.parse_args()
    ServiceGraph(args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

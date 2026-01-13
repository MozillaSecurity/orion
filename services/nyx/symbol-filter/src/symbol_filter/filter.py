# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Filters symbol paths for use with AFL Dynamic PC Filter"""

import os
import re
import tempfile
from argparse import ArgumentParser
from dataclasses import dataclass
from enum import Enum
from logging import DEBUG, INFO, basicConfig, getLogger
from pathlib import Path
from typing import TypedDict

from fuzzfetch import BuildFlags, Fetcher, download_url
from Reporter.Reporter import Reporter, remote_checks

LOG = getLogger(__name__)

# Constants
SOURCE_PREFIX = "/builds/worker/checkouts/gecko/"
DIST_INCLUDE_PREFIX = "/builds/worker/workspace/obj-build/dist/include/"
MOZSEARCH_ARTIFACT = "mozsearch-distinclude.map"


class SymbolFilterException(Exception):
    """Exception raised for symbol filtering errors."""


class FilterType(Enum):
    """Filter action types for include/exclude patterns."""

    INCLUDE = 1
    EXCLUDE = 2


class ReportConfigurationResult(TypedDict):
    """The result returned from FuzzManager."""

    id: int
    directives: str


@dataclass
class FilterPattern:
    """A filter pattern."""

    type: FilterType
    pattern: str


class ReportConfiguration(Reporter):  # type: ignore[misc]
    """Fetches report configuration from FuzzManager API."""

    def __init__(self) -> None:
        """Initializes ReportConfiguration."""
        super().__init__(tool="symbol-filter")

    @remote_checks  # type: ignore[untyped-decorator]
    def get_report_configuration(self, ident: int) -> ReportConfigurationResult:
        """Fetch report configuration by ID from the API."""
        url = (
            f"{self.serverProtocol}://{self.serverHost}:"
            f"{self.serverPort}/covmanager/rest/reportconfigurations/{ident}"
        )

        return self.get(url).json()  # type: ignore[no-untyped-call, no-any-return]


def load_filter_patterns(filter_spec: int | Path) -> list[FilterPattern]:
    """Load filter patterns from remote report configuration or local file."""
    if isinstance(filter_spec, int):
        LOG.info("Requesting report configuration...")
        reporter = ReportConfiguration()
        configuration = reporter.get_report_configuration(filter_spec)
        directives = configuration["directives"]
    else:
        LOG.info("Reading filter from local file: %s", filter_spec)
        with open(filter_spec, encoding="utf-8") as f:
            directives = f.read()

    patterns = []
    for directive in directives.splitlines():
        directive = directive.strip()
        if not directive or directive.startswith("#"):
            continue

        if directive.startswith("+:"):
            pattern = directive[2:].strip()
            patterns.append(FilterPattern(FilterType.INCLUDE, pattern))
        elif directive.startswith("-:"):
            pattern = directive[2:].strip()
            patterns.append(FilterPattern(FilterType.EXCLUDE, pattern))
        else:
            raise SymbolFilterException("Invalid filter type directive!")

    return patterns


def load_path_map() -> dict[str, str]:
    """Load the path mapping from mozsearch-distinclude.map format."""
    mapping = {}

    LOG.info("Downloading include map...")
    flags = BuildFlags(searchfox=True)
    fetcher = Fetcher("central", "latest", flags, ["searchfox"])
    with tempfile.TemporaryDirectory() as tmp_dir:
        url = fetcher.artifact_url(MOZSEARCH_ARTIFACT)
        temp_file = Path(tmp_dir) / MOZSEARCH_ARTIFACT
        download_url(url, outfile=temp_file)

        with open(temp_file, encoding="utf-8") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            # Format: <type><dist_path><source_path> (tab-separated with \x1f)
            if SOURCE_PREFIX in line:
                parts = line.split("\x1f")
                assert len(parts) == 3, (
                    f"Malformed entry in {MOZSEARCH_ARTIFACT} at line ${idx}"
                )
                _, dist_path, source_path = parts
                mapping[dist_path] = source_path

    return mapping


def matches_pattern(path: str, pattern: str) -> bool:
    """
    Determine if the supplied path matches the given pattern.
    :param path: The path to evaluate.
    :param pattern: The pattern to match.
    """
    # Escape special regex characters except * and **
    # Replace ** with a placeholder first
    return (
        re.fullmatch(
            re.escape(pattern)
            .replace(r"\*\*", ".*")  # ** matches anything including /
            .replace(r"\*", "[^/]*"),  # * matches anything except /
            path,
        )
        is not None
    )


def should_include_path(path: str, patterns: list[FilterPattern]) -> bool:
    """
    Determine if a path should be included based on filter patterns.
    :param path: The path to evaluate.
    :param patterns: The patterns to match.
    """
    # last matching pattern wins
    for filter_pattern in reversed(patterns):
        if matches_pattern(path, filter_pattern.pattern):
            if filter_pattern.type == FilterType.INCLUDE:
                return True
            elif filter_pattern.type == FilterType.EXCLUDE:
                return False

    return False


def resolve_symbol_path(symbol_path: str, path_map: dict[str, str]) -> str | None:
    """
    Resolve a symbol file path to its source tree location.

    Handles two cases:
    1. Find absolute path for includes.
    2. Strip local build path to get relative source tree path.
    """
    if symbol_path.startswith(SOURCE_PREFIX):
        return symbol_path[len(SOURCE_PREFIX) :]

    if symbol_path.startswith(DIST_INCLUDE_PREFIX):
        dist_relative = symbol_path[len(DIST_INCLUDE_PREFIX) :]
        return path_map.get(dist_relative)

    return None


def filter_symbols(
    symbol_path: Path,
    filter_spec: int | Path,
) -> list[str]:
    """
    Filter symbols based on filter patterns.
    :param symbol_path: Symbol file path.
    :param filter_spec: Fuzzmanager report configuration identifier or local file path.
    """
    patterns = load_filter_patterns(filter_spec)
    LOG.info("Loaded %d filter patterns", len(patterns))

    path_map = load_path_map()
    LOG.info("Loaded %d path mappings", len(path_map))

    matched_symbols = []
    total_symbols = 0
    resolved_symbols = 0

    with symbol_path.open("r") as f:
        for idx, line in enumerate(f, start=1):
            total_symbols += 1
            line = line.rstrip("\n")

            # Parse symbol: <address>\t<size>\t<library>\t<file_path>\t<symbol_name>
            parts = line.split("\t")
            if len(parts) < 4:
                raise SymbolFilterException(
                    f"Symbol map contains unexpected number of columns at line ${idx}!"
                )

            file_path = parts[3]

            # Resolve to source tree path
            source_path = resolve_symbol_path(file_path, path_map)

            if source_path is None:
                continue

            resolved_symbols += 1

            # Check if path matches filter
            if should_include_path(source_path, patterns):
                matched_symbols.append(line)

    LOG.info("Total symbols: %d", total_symbols)
    LOG.info("Resolved symbols: %d", resolved_symbols)
    LOG.info("Matched symbols: %d", len(matched_symbols))

    return matched_symbols


def main() -> int:
    """Main entry point for the symbol filter CLI."""
    log_level = INFO
    log_fmt = "%(message)s"
    if bool(os.getenv("DEBUG")):
        log_level = DEBUG
        log_fmt = "%(levelname).1s %(name)s [%(asctime)s] %(message)s"
    basicConfig(format=log_fmt, datefmt="%Y-%m-%d %H:%M:%S", level=log_level)

    parser = ArgumentParser(description="Filter symbols based on source file patterns")
    parser.add_argument(
        "symbol_path",
        type=Path,
        help="Path to symbol file",
    )
    parser.add_argument(
        "filter",
        type=str,
        help="Fuzzmanager coverage report configuration ID or path to local file",
    )
    parser.add_argument("--local-path", type=Path, help="Local source path")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output path",
    )

    args = parser.parse_args()
    if not args.symbol_path.exists():
        parser.error(f"Symbol path does not exist: {args.symbol_path}")

    if not args.symbol_path.is_file():
        parser.error(f"Path is not a file: {args.symbol_path}")

    # Determine if filter is an integer or a file path
    try:
        filter_spec: int | Path = int(args.filter)
    except ValueError:
        filter_spec = Path(args.filter)
        if not filter_spec.exists():
            parser.error(f"Filter file does not exist: {filter_spec}")
        if not filter_spec.is_file():
            parser.error(f"Filter path is not a file: {filter_spec}")

    result = filter_symbols(args.symbol_path, filter_spec, args.local_path)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            for line in result:
                print(line, file=f)
    else:
        for line in result:
            print(line)

    return 0

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests for symbol_filter.filter module."""

from unittest.mock import patch

# Suppress decorator before loading Reporter
patch("Reporter.Reporter.remote_checks", lambda f: f).start()

import pytest

from symbol_filter.filter import (
    FilterPattern,
    FilterType,
    SymbolFilterException,
    filter_symbols,
    load_filter_patterns,
    load_path_map,
    matches_pattern,
    resolve_symbol_path,
    should_include_path,
)


@pytest.fixture
def mock_fuzzfetch(mocker):
    """Mock fuzzfetch components to avoid network calls."""

    def setup_mocks(lines: list[str]) -> None:
        # Mock download_url to write fixture data to the temp file
        def mock_download_url(_url: str, outfile: object) -> None:
            outfile.write_text("\n".join(lines))  # type: ignore[attr-defined]

        # Mock Fetcher to do nothing but return a mock URL
        mock_fetcher = mocker.MagicMock()
        mock_fetcher.artifact_url.return_value = (
            "http://mock.url/mozsearch-distinclude.map"
        )

        mocker.patch("symbol_filter.filter.download_url", side_effect=mock_download_url)
        mocker.patch("symbol_filter.filter.Fetcher", return_value=mock_fetcher)
        mocker.patch("symbol_filter.filter.BuildFlags")

    return setup_mocks


@pytest.fixture
def mock_report_configuration(mocker):
    """
    Mock ReportConfiguration to avoid network calls and return fixture data.
    Mocks the underlying Reporter.get() method to prevent network requests.
    """

    def setup_mocks(directives: str, config_id: int = 1) -> None:
        # Create mock response object with json() method
        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"id": config_id, "directives": directives}

        # Mock Reporter.get() to return the mock response
        mocker.patch("symbol_filter.filter.Reporter.get", return_value=mock_response)

    return setup_mocks


def test_load_filter_patterns_basic(mock_report_configuration) -> None:
    """Test loading filter patterns from report configuration."""
    mock_report_configuration(
        "\n".join(
            [
                "# Include the following",
                "+:include_this/**",
                "# Exclude the following",
                "-:exclude_that/*.py",
            ]
        )
    )

    patterns = load_filter_patterns(filter_id=1)
    assert patterns == [
        FilterPattern(FilterType.INCLUDE, "include_this/**"),
        FilterPattern(FilterType.EXCLUDE, "exclude_that/*.py"),
    ]


def test_load_filter_patterns_invalid_line_raises(mock_report_configuration) -> None:
    """Test that invalid directives raise an exception."""
    directives = "something invalid"
    mock_report_configuration(directives)

    with pytest.raises(SymbolFilterException, match="Invalid filter type directive"):
        load_filter_patterns(filter_id=1)


def test_load_path_map_basic(mock_fuzzfetch) -> None:
    """Test loading path map from mozsearch-distinclude.map format."""
    mock_fuzzfetch(
        [
            "5",  # header line skipped
            "1\x1fVideoUtils.h\x1f/builds/worker/checkouts/gecko/dom/media/VideoUtils.h",
            "",  # blank line skipped
            "1\x1fNotRelevant.h\x1f/not/a/gecko/path",  # doesn't include dist path
        ]
    )

    mapping = load_path_map()
    assert mapping == {
        "VideoUtils.h": "/builds/worker/checkouts/gecko/dom/media/VideoUtils.h",
    }


def test_load_path_map_asserts_on_malformed_line(mock_fuzzfetch) -> None:
    """Test that malformed lines raise an AssertionError."""
    mock_fuzzfetch(["1\x1f/builds/worker/checkouts/gecko/VideoUtils.h"])

    with pytest.raises(AssertionError):
        load_path_map()


def test_load_path_map_resolve_direct_source_path() -> None:
    """Test resolving direct source paths from gecko checkout."""
    path_map: dict[str, str] = {}
    symbol_path = "/builds/worker/checkouts/gecko/dom/media/VideoUtils.h"

    result = resolve_symbol_path(symbol_path, path_map)

    assert result == "dom/media/VideoUtils.h"


def test_load_path_map_resolve_dist_include_path_found() -> None:
    """Test resolving dist/include paths using the path map."""
    path_map: dict[str, str] = {
        "VideoUtils.h": "dom/media/VideoUtils.h",
    }
    symbol_path = "/builds/worker/workspace/obj-build/dist/include/VideoUtils.h"

    result = resolve_symbol_path(symbol_path, path_map)

    assert result == "dom/media/VideoUtils.h"


def test_load_path_map_resolve_dist_include_path_not_found() -> None:
    """Test that unknown paths return None."""
    path_map: dict[str, str] = {}
    symbol_path = "VideoUtils.h"

    result = resolve_symbol_path(symbol_path, path_map)

    assert result is None


@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        # Exact match
        ("foo/bar.cpp", "foo/bar.cpp", True),
        ("foo/bar.cpp", "foo/baz.cpp", False),
        # ** matches zero or more directory segments
        ("dom/webgpu/Adapter.cpp", "dom/webgpu/**", True),
        ("dom/webgpu/Adapter.cpp", "dom/**/Adapter.cpp", True),
        ("dom/webgpu/Adapter.cpp", "dom/**", True),
        ("dom/media/File.cpp", "dom/webgpu/**", False),
        # * matches single segment only (not /)
        ("foo/a/bar.cpp", "foo/*/bar.cpp", True),
        ("foo/a/b/bar.cpp", "foo/*/bar.cpp", False),
        # * in filename
        ("foo/bar.cpp", "foo/*.cpp", True),
        ("foo/subdir/file.cpp", "foo/*.cpp", False),
        # * for partial names
        (
            "third_party/rust/wgpu-core/src/lib.rs",
            "third_party/rust/wgpu-*/src/**",
            True,
        ),
        # Special regex chars escaped
        ("foo/bar.cpp", "foo/bar.cpp", True),
        ("foo/barXcpp", "foo/bar.cpp", False),
    ],
)
def test_matches_pattern(path: str, pattern: str, expected: bool) -> None:
    """Test glob pattern matching with ** and *."""
    assert matches_pattern(path, pattern) == expected


@pytest.mark.parametrize(
    "path,patterns,expected",
    [
        # No patterns - default False
        ("foo/bar.cpp", [], False),
        # Single include
        ("foo/bar.cpp", [(FilterType.INCLUDE, "foo/bar.cpp")], True),
        ("baz.cpp", [(FilterType.INCLUDE, "foo/bar.cpp")], False),
        # Single exclude
        ("foo/bar.cpp", [(FilterType.EXCLUDE, "foo/bar.cpp")], False),
        # Last matching pattern wins
        (
            "dom/webgpu/file.cpp",
            [(FilterType.EXCLUDE, "**"), (FilterType.INCLUDE, "dom/webgpu/**")],
            True,
        ),
        (
            "dom/webgpu/file.cpp",
            [(FilterType.INCLUDE, "dom/**"), (FilterType.EXCLUDE, "dom/webgpu/**")],
            False,
        ),
    ],
)
def test_should_include_path(
    path: str, patterns: list[FilterPattern], expected: bool
) -> None:
    """Test filter pattern application with last-match-wins semantics."""
    assert should_include_path(path, patterns) == expected


def test_filter_symbols_basic(
    tmp_path, mock_report_configuration, mock_fuzzfetch
) -> None:
    """Test basic symbol filtering with patterns and path resolution."""
    # Create symbol file with various paths
    symbol_file = tmp_path / "symbols.txt"
    symbol_file.write_text(
        "0x1000\t100\tlib.so\t"
        "/builds/worker/checkouts/gecko/dom/webgpu/Adapter.cpp\tsymbol1\n"
        "0x2000\t200\tlib.so\t"
        "/builds/worker/checkouts/gecko/dom/media/VideoUtils.cpp\tsymbol2\n"
        "0x3000\t300\tlib.so\t"
        "/builds/worker/workspace/obj-build/dist/include/VideoUtils.h\tsymbol3\n"
        "0x4000\t400\tlib.so\t/unknown/path/file.cpp\tsymbol4\n"
    )

    # Setup mocks
    mock_report_configuration("+:dom/webgpu/**")
    mock_fuzzfetch(
        ["1\x1fVideoUtils.h\x1f/builds/worker/checkouts/gecko/dom/media/VideoUtils.h"]
    )

    result = filter_symbols(symbol_file, filter_id=1)

    # Only webgpu path should match
    assert len(result) == 1
    assert "dom/webgpu/Adapter.cpp" in result[0]


def test_filter_symbols_with_exclusions(
    tmp_path, mock_report_configuration, mock_fuzzfetch
) -> None:
    """Test symbol filtering with include and exclude patterns."""
    symbol_file = tmp_path / "symbols.txt"
    symbol_file.write_text(
        "0x1000\t100\tlib.so\t"
        "/builds/worker/checkouts/gecko/dom/webgpu/Adapter.cpp\tsymbol1\n"
        "0x2000\t200\tlib.so\t"
        "/builds/worker/checkouts/gecko/dom/media/VideoUtils.cpp\tsymbol2\n"
        "0x3000\t300\tlib.so\t"
        "/builds/worker/checkouts/gecko/gfx/layers/Layer.cpp\tsymbol3\n"
    )

    directives = "+:dom/**\n-:dom/media/**"
    mock_report_configuration(directives)
    mock_fuzzfetch([])

    result = filter_symbols(symbol_file, filter_id=1)

    # Should match webgpu but not media
    assert len(result) == 1
    assert "dom/webgpu" in result[0]


def test_filter_symbols_malformed_line(
    tmp_path, mock_report_configuration, mock_fuzzfetch
) -> None:
    """Test that malformed symbol lines raise an exception."""
    symbol_file = tmp_path / "symbols.txt"
    symbol_file.write_text("0x1000\t100\tlib.so\n")  # Missing file_path column

    mock_report_configuration("+:**")
    mock_fuzzfetch([])

    with pytest.raises(
        SymbolFilterException, match="Symbol map contains unexpected number"
    ):
        filter_symbols(symbol_file, filter_id=1)

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Union

import yaml
from jsonschema import validate
from referencing import Registry, Resource

PathArg = Union[str, Path]


def _load_schema_cache() -> Registry:
    resources = []
    for path in (Path(__file__).parent.parent / "schemas").glob("*.yaml"):
        schema = Resource.from_contents(yaml.safe_load(path.read_text()))
        uri = schema.id()
        assert uri is not None
        resources.append((uri, schema))
    return Registry().with_resources(resources)


SCHEMA_CACHE = _load_schema_cache()


def _schema_by_name(name: str):
    for uri in SCHEMA_CACHE:
        schema = SCHEMA_CACHE[uri]
        if schema.contents["title"] == name:
            return schema.contents
    raise RuntimeError(f"Unknown schema name: {name}")  # pragma: no cover


def validate_schema_by_name(instance: dict[str, str] | str, name: str):
    schema = _schema_by_name(name)
    return validate(instance=instance, schema=schema, registry=SCHEMA_CACHE)


def onerror(func: Callable[[PathArg], None], path: PathArg, _exc_info: Any) -> None:
    """Error handler for `shutil.rmtree`.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Copyright Michael Foord 2004
    Released subject to the BSD License
    ref: http://www.voidspace.org.uk/python/recipebook.shtml#utils

    Usage : `shutil.rmtree(path, onerror=onerror)`
    """
    if not os.access(path, os.W_OK):
        # Is the error an access error?
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        # this should only ever be called from an exception context
        raise  # pylint: disable=misplaced-bare-raise


def parse_size(size: str) -> float:
    """Parse a human readable size like "4g" into (4 * 1024 * 1024 * 1024)

    Args:
        size: size as a string, with si prefixes allowed

    Returns:
        size with si prefix expanded
    """
    match = re.match(r"(\d+\.\d+|\d+)([kmgt]?)b?", size, re.IGNORECASE)
    assert match is not None, "size should be a number followed by optional si prefix"
    result = float(match.group(1))
    multiplier = {
        "": 1,
        "k": 1024,
        "m": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "t": 1024 * 1024 * 1024 * 1024,
    }[match.group(2).lower()]
    return result * multiplier


def parse_time(time: str) -> int:
    """Parse a human readable time like 1h30m or 30m10s

    Args:
        time: time as a string

    Returns:
        time in seconds
    """
    result = 0
    got_anything = False
    while time:
        match = re.match(r"(\d+)([wdhms]?)(.*)", time, re.IGNORECASE)
        assert match is not None, "time should be a number followed by optional unit"
        if match.group(2):
            multiplier = {
                "w": 7 * 24 * 60 * 60,
                "d": 24 * 60 * 60,
                "h": 60 * 60,
                "m": 60,
                "s": 1,
            }[match.group(2).lower()]
        else:
            assert not match.group(3), "trailing data"
            assert not got_anything, "multipart time must specify all units"
            multiplier = 1
        got_anything = True
        result += int(match.group(1)) * multiplier
        time = match.group(3)
    assert got_anything, "no time could be parsed"
    return result

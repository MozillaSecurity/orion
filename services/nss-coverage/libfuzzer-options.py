#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import tomllib


def main():
    with open(sys.argv[1], "rb") as f:
        toml = tomllib.load(f)

    print("\n".join(
        map(lambda item: f"-{item[0]}={item[1]}", toml["libfuzzer"].items())))


if __name__ == "__main__":
    main()

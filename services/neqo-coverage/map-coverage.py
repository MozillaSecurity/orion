#!/usr/bin/env python

import json
import sys

def translate_fn(fn):
    if fn.startswith("neqo-"):
        return f"third_party/rust/{fn}"
    return fn

def main():
    with open(sys.argv[1], "r") as f:
        data = json.load(f)

    for obj in data["source_files"]:
        obj["name"] = translate_fn(obj["name"])

    json.dump(data, sys.stdout)

if __name__ == "__main__":
    main()

import json
import sys

data = None

def translate_fn(fn):
    if fn.startswith("nss/"):
        return f"security/nss/{fn[4:]}"
    if fn.startswith("pr/") or fn.startswith("lib/") or fn.startswith("config/"):
        return f"nsprpub/{fn}"
    return fn

for inp in sys.argv[1:]:
    with open(inp) as fd:
        if data is None:
            data = json.load(fd)
            data["source_files"] = {
                translate_fn(obj["name"]): obj
                for obj in data["source_files"]
            }
            for fn, obj in data["source_files"].items():
                obj["name"] = fn
        else:
            new = json.load(fd)
            for obj in new["source_files"]:
                fn = translate_fn(obj["name"])
                if fn in data["source_files"]:
                    old = data["source_files"][fn]
                    for idx, (oldn, newn) in enumerate(zip(old["coverage"], obj["coverage"])):
                        if oldn or newn:
                            oldn += newn
                            old["coverage"][idx] = newn
                else:
                    data["source_files"][fn] = obj
                    obj["name"] = fn

data["source_files"] = list(data["source_files"].values())
json.dump(data, sys.stdout)

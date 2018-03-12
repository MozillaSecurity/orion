#!/usr/bin/env python
# coding=utf-8
"""
Choose a random target based on JSON config files
"""
from __future__ import print_function
import argparse
import collections
import json
import logging
import os
import platform
import random


CONFIG_PATH = os.path.realpath(os.path.dirname(__file__))
DEFAULT = "default-32.json" if platform.machine() == "i686" else "default.json"


def main(argv=None):
    """
    Choose a random target based on JSON config files
    """
    logging.basicConfig(format="%(message)s")
    log = logging.getLogger("targets.rand")

    aparser = argparse.ArgumentParser()
    aparser.add_argument("toolname", help="FuzzManager toolname, used to look for configs")
    args = aparser.parse_args(args=argv)

    ext = "-32.json" if platform.machine() == "i686" else ".json"
    cfg_path = os.path.join(CONFIG_PATH, args.toolname + ext)
    if not os.path.isfile(cfg_path):
        cfg_path = os.path.join(CONFIG_PATH, DEFAULT)
        log.warning("\"%s\" has no config, using default: %s", args.toolname, cfg_path)
        assert os.path.isfile(cfg_path), "missing default config file: %s" % cfg_path
    else:
        log.info("\"%s\" has a config: %s", args.toolname, cfg_path)
    with open(cfg_path) as cfg_fp:
        cfg = json.load(cfg_fp, object_hook=collections.OrderedDict)

    total_weight = 0
    for target, weight in cfg.items():
        assert int(weight) == weight, "only integer weights are supported, got: %r" % weight
        assert weight >= 0, "only positive weights are supported"
        if weight == 0:
            log.warning("target \"%s\" -> weight=0, will not be selected", target)
        else:
            log.info("target \"%s\" -> weight=%d", target, weight)
        total_weight += int(weight)
    log.debug("total weight: %d", total_weight)
    assert total_weight > 0, "no targets given?"

    selected_weight = random.randrange(total_weight)
    log.debug("selected weight: %d", selected_weight)
    for target, weight in cfg.items():
        selected_weight -= weight
        if selected_weight < 0:
            log.debug("chosen target: \"%s\"", target)
            print(target)
            return 0

    raise Exception("weight error: %d remains of %d" % (selected_weight, total_weight))


if __name__ == "__main__":
    exit(main())

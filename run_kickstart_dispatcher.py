#!/usr/bin/python3

import os
import sys

#export PYTHONPATH=/home/rvykydal/git/rvykydal/anaconda/:/home/rvykydal/git/rvykydal/pykickstart ; ./run_kickstart_dispatcher.py ks.include.cfg

try:
    ksfile = sys.argv[1]
except IndexError:
    ksfile = "ks.cfg"

from pyanaconda.kickstart_dispatcher import split_kickstart

valid_sections = [
                      "%pre",
                      "%pre-install",
                      "%post",
                      "%onerror",
                      "%traceback",
                      "%packages",
                      "%addon",
                      "%anaconda",
                     ]
commands = ["network", "timezone"]
sections = ["%packages", "%post"]
split_kickstart(ksfile, valid_sections, commands, sections)


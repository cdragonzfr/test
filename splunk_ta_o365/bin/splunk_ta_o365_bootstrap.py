#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
try:
    import http.client
    import queue
    import copyreg
except:
    pass
import os
import os.path
import re
import sys
import logging


def setup_python_path():
    # Exclude folder beneath other apps, Fix bug for rest_handler.py
    # Exclude folder beneath other apps, Fix bug for rest_handler.py
    ta_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
    pattern = re.compile(r"[\\/]etc[\\/]apps[\\/][^\\/]+[\\/]bin[\\/]?$")
    new_paths = [
        path for path in sys.path if not pattern.search(path) or ta_name in path
    ]
    new_paths.insert(0, os.path.dirname(__file__))
    sys.path = new_paths

    sys.path.insert(0, os.path.realpath(os.path.dirname(__file__)))
    # We sort the precedence in a decending order since sys.path.insert(0, ...)
    # do the reversing.
    # Insert library folder
    sys.path.insert(
        0,
        os.path.sep.join(
            [os.path.dirname(os.path.realpath(os.path.dirname(__file__))), "lib"]
        ),
    )


# preventing splunklib initialize an unexpected root handler
def setup_null_handler():
    logging.root.addHandler(logging.NullHandler())


def run_module(name):
    setup_python_path()
    setup_null_handler()
    instance = __import__(name, fromlist=["main"])
    instance.main()


setup_python_path()
setup_null_handler()

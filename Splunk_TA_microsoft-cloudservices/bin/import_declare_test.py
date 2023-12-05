#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import os
import sys
import http
import queue
import typing
import concurrent.futures
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(
    0,
    os.path.sep.join(
        [os.path.dirname(os.path.realpath(os.path.dirname(__file__))), "lib"]
    ),
)
if sys.version_info < (3, 0):
    sys.path.insert(
        0,
        os.path.sep.join(
            [os.path.dirname(os.path.realpath(os.path.dirname(__file__))), "lib", "py2"]
        ),
    )
else:
    sys.path.insert(
        0,
        os.path.sep.join(
            [os.path.dirname(os.path.realpath(os.path.dirname(__file__))), "lib", "py3"]
        ),
    )

bindir = os.path.dirname(os.path.realpath(os.path.dirname(__file__)))
libdir = os.path.join(bindir, "lib", "3rdparty")
platform = sys.platform
if platform.startswith("win32"):
    platfrom_folder = "windows_x86_64"
elif platform.startswith("darwin"):
    platfrom_folder = "darwin_x86_64"
else:
    platfrom_folder = "linux_x86_64"
sharedpath = os.path.join(libdir, platfrom_folder, "python3")
sys.path.insert(0, sharedpath)


if sys.version_info < (3, 0):
    # using __file__ attribute as it is common between http and queue
    assert "Splunk_TA_microsoft-cloudservices" in http.__file__
    assert "Splunk_TA_microsoft-cloudservices" in queue.__file__
    assert "Splunk_TA_microsoft-cloudservices" in typing.__file__
    assert "Splunk_TA_microsoft-cloudservices" in concurrent.futures.__file__

else:
    assert "Splunk_TA_microsoft-cloudservices" not in http.__file__
    assert "Splunk_TA_microsoft-cloudservices" not in queue.__file__
    assert "Splunk_TA_microsoft-cloudservices" not in typing.__file__
    assert "Splunk_TA_microsoft-cloudservices" not in concurrent.futures.__file__

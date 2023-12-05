#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from future import standard_library

standard_library.install_aliases()
from builtins import object
import queue
import multiprocessing
import copy


class DataWriter(object):

    QUEUE_SIZE = 1000

    TIMEOUT = 3

    def __init__(self, process_safe=False):
        if process_safe:
            self._mgr = multiprocessing.Manager()
            self._data_queue = self._mgr.Queue(self.QUEUE_SIZE)
        else:
            self._data_queue = queue.Queue(self.QUEUE_SIZE)

    def write_events(self, events, canceled=None):
        return self.write_events_and_ckpt(events, None, None, canceled)

    def write_ckpt(self, key, ckpt, canceled=None):
        return self.write_events_and_ckpt(None, key, ckpt, canceled)

    def write_events_and_ckpt(self, events, key, ckpt, canceled=None):
        if canceled is None:
            self._data_queue.put(item=(events, key, copy.deepcopy(ckpt)))
        elif canceled.is_set():
            return
        else:
            while True:
                try:
                    self._data_queue.put(
                        item=(events, key, copy.deepcopy(ckpt)), timeout=self.TIMEOUT
                    )
                    break
                except queue.Full:
                    if canceled.is_set():
                        break

    def get_data(self, block=True, timeout=None):
        return self._data_queue.get(block, timeout)

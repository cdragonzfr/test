#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from builtins import next
import splunktaucclib.data_collection.ta_data_client as dc

import mscs_storage_table_list_data_collector as mstldc


class StorageTableDataClient(dc.TaDataClient):
    def __init__(self, all_conf_contents, meta_config, task_config, ckpt, chp_mgr):
        super(StorageTableDataClient, self).__init__(
            all_conf_contents, meta_config, task_config, ckpt, chp_mgr
        )
        self._execute_times = 0
        self._gen = self.get_contents()

    def stop(self):
        """
        overwrite to handle stop control command
        """

        # normaly base class just set self._stop as True
        super(StorageTableDataClient, self).stop()

    def get(self):
        """
        overwrite to get events
        """
        self._execute_times += 1
        if self.is_stopped():
            self._gen.send(self.is_stopped())
            raise StopIteration
        if self._execute_times == 1:
            return next(self._gen)
        return self._gen.send(self.is_stopped())

    def get_contents(self):
        data_collector = mstldc.StorageTableListDataCollector(
            self._all_conf_contents, self._meta_config, self._task_config
        )
        return data_collector.collect_data()

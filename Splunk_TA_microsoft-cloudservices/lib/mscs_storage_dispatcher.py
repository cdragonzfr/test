#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import abc
import concurrent.futures as cf
import json
import os.path as op
import os
import threading
import requests

import mscs_checkpoint_util as cutil
import mscs_checkpointer as mc
import mscs_consts
from future.utils import with_metaclass  # pylint: disable=import-error

# if the key can not be stored by kvstore
# ie: invalid key name
class BlobKeyError(Exception):
    def __init__(self, blob_name):
        self.blob_name = blob_name


# if another process is run this key.
class BlobKeyBusy(Exception):
    def __init__(self, blob_name):
        self.blob_name = blob_name


class StorageDispatcher(with_metaclass(abc.ABCMeta, object)):  # type: ignore
    DEFAULT_WORKER_THREADS_NUM = 10

    def __init__(
        self,
        all_conf_contents,
        meta_config,
        task_config,
        data_writer,
        logger,
        use_kv=False,
    ):
        self._all_conf_contents = all_conf_contents
        self._meta_config = meta_config
        self._task_config = task_config
        self._data_writer = data_writer
        self._logger = logger

        self._checkpointer = self._create_checkpointer(use_kv)
        self._worker_threads_num = int(
            self._all_conf_contents[mscs_consts.GLOBAL_SETTINGS][
                mscs_consts.PERFORMANCE_TUNING_SETTINGS
            ].get(mscs_consts.WORKER_THREADS_NUM, self.DEFAULT_WORKER_THREADS_NUM)
        )
        self._executor = None
        self._storage_dispatcher = threading.Thread(target=self._dispatch_storage_list)
        self._canceled = threading.Event()
        self._sub_canceled_lst = []

    def start(self):
        self._logger.info("worker_threads_num=%s", self._worker_threads_num)
        self._executor = cf.ThreadPoolExecutor(max_workers=self._worker_threads_num)
        self._storage_dispatcher.start()

    def cancel(self):
        self._canceled.set()

    def is_alive(self):
        return self._storage_dispatcher.isAlive()  # pylint: disable=no-member

    def get_checkpointer(self):
        return self._checkpointer

    @abc.abstractmethod
    def _get_patterns(self):
        pass

    @abc.abstractmethod
    def _get_ckpt(self, storage_info):
        pass

    @abc.abstractmethod
    def _get_sub_task_config(self, storage_info, ckpt):
        pass

    @abc.abstractmethod
    def _get_running_task(self):
        pass

    @abc.abstractmethod
    def _union_storage_name_set(self, storage_name_set, storage_info_lst):
        pass

    @abc.abstractmethod
    def _dispatch_tasks(self, patterns):
        pass

    def _dispatch_storage_list(self):
        try:
            self._logger.info("Starting to dispatch storage list")
            self._do_dispatch()
            self._logger.info("Finished dispatching storage list.")
        except Exception as e:
            self._logger.exception(
                "Exception@_dispatch_tables() ,error_message=%s", str(e)
            )
            for sub_canceled in self._sub_canceled_lst:
                sub_canceled.set()
            self._executor.shutdown()

    def _do_dispatch(self):
        patterns = self._get_patterns()
        self._dispatch_tasks(patterns)

    def _do_migration(self):
        pass

    def _create_checkpointer(self, use_kv=False):
        """
        creates Checkpointer
        this checkpointer should be the only one for blobstore

        if _get_checkpoint_dir returns an exisiting directory then
        we create the FileCheckpointer class for migration
        """

        checkpoint_dir, input_id = self._get_checkpoint_dir()

        if not use_kv:
            return mc.FileCheckpointer(checkpoint_dir)

        return mc.KVCheckpointer(
            self._meta_config,
            input_id=input_id,
        )

    def _get_checkpoint_dir(self):
        account_stanza_name = self._task_config[mscs_consts.ACCOUNT]
        account_info = self._all_conf_contents[mscs_consts.ACCOUNTS][
            account_stanza_name
        ]
        account_name = account_info.get(mscs_consts.ACCOUNT_NAME)
        qualified_dir_name = cutil.get_checkpoint_name(
            (self._task_config[mscs_consts.STANZA_NAME], account_name)
        )
        return (
            op.join(self._meta_config[mscs_consts.CHECKPOINT_DIR], qualified_dir_name),
            cutil.get_checkpoint_name(
                (
                    self._task_config.get(mscs_consts.CONTAINER_NAME, "-"),
                    account_name,
                    self._get_index_name(),
                )
            ),
        )

    def _get_index_name(self):
        """Used to get the name of the Index.

        Returns:
            str: Name of the index.
        """
        index = self._task_config.get(mscs_consts.INDEX, "-")
        try:
            if index == "default":
                url: str = "{}/services/data/indexes?output_mode=json&count=1".format(
                    self._meta_config["server_uri"],
                )
                headers = {
                    "Authorization": "Bearer {}".format(
                        self._meta_config["session_key"]
                    ),
                }

                response = requests.get(url, headers=headers, verify=False)
                if response.status_code == 200:
                    indexes = response.json()
                    index = indexes["entry"][0]["content"]["defaultDatabase"]
        except:
            self._logger.info(
                "Could not find default index. Using 'default' and checkpoint key"
            )
        return index

    def _wait_while_full(self, fs, max_threads):
        """
        Waits while threads running are greater than max_threads * 2

        fs:  a list of futures
        max_threads: max number of threads to run

        returns: list of still running futures(threads)

        """
        while len(fs) > (max_threads * 2):
            res = cf.wait(fs=fs, timeout=1000, return_when=cf.FIRST_COMPLETED)
            fs = list(res.not_done)
        return fs

    def _wait_fs(self, fs):
        while True:
            res = cf.wait(fs=fs, timeout=10, return_when=cf.ALL_COMPLETED)
            if not res.not_done:
                break
            if self._canceled.is_set():
                break

    def _cancel_sub_tasks(self, canceled, sub_canceled_list=[]):
        if canceled.is_set():
            for sub_canceled in sub_canceled_list:
                sub_canceled.set()
            self._executor.shutdown()
            return True
        return False

    def send_notification(self, name: str, message: str) -> None:
        """
        Used to send the notification splunk UI.
        :param name: message name or key.
        :type input_name: ``string``
        :param message: message value.
        :type input_name: ``string``
        """
        url: str = "{}/services/messages".format(
            self._meta_config["server_uri"],
        )
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Bearer {}".format(self._meta_config["session_key"]),
        }
        payload = {
            "name": name,
            "value": message,
            "severity": "info",
        }
        response = requests.post(url, data=payload, headers=headers, verify=False)
        if response.status_code == 201:
            self._logger.info("Successfully sent the notification.")
        else:
            self._logger.warn("Failed to send the notification.")

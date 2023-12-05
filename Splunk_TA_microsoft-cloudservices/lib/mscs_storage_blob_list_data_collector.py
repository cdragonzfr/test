#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from future import standard_library

standard_library.install_aliases()
from builtins import object
import queue
import time

import mscs_consts
import mscs_data_writer as mdw
import mscs_logger as logger
import mscs_storage_blob_dispatcher as msbd
import os
import threading
import requests
from mscs_util import get_conf_file_info


class StorageBlobListDataCollector(object):
    TIMEOUT = 3
    BATCH_FLUSH_TIMEOUT = 120

    def __init__(self, all_conf_contents, meta_config, task_config):
        self._all_conf_contents = all_conf_contents
        self._meta_config = meta_config
        self._task_config = task_config
        self._data_writer = mdw.DataWriter()
        self._logger = logger.logger_for(self._get_logger_prefix())

        self._task_config["is_migrated"] = self._get_migration_status()

        self._storage_dispatcher = msbd.StorageBlobDispatcher(
            all_conf_contents, meta_config, task_config, self._data_writer, self._logger
        )
        self._checkpointer = self._storage_dispatcher.get_checkpointer()
        self.checkpoint_dir, _ = self._storage_dispatcher._get_checkpoint_dir()

    def update_migration_flag(self, key, value) -> None:
        """Updates the value of the flag

        Args:
            key (str): name of the flag
            value (str): value of the flag
        """

        # Encode the url as per the ASCII standard
        stanza_name = "mscs_storage_blob://" + self._task_config["stanza_name"]
        encoded_stanza_name: str = requests.utils.quote(stanza_name, safe="")
        # build url using app object
        url: str = "{}/servicesNS/nobody/Splunk_TA_microsoft-cloudservices/configs/conf-inputs/{}".format(
            self._meta_config["server_uri"],
            encoded_stanza_name,
        )
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Bearer {}".format(self._meta_config["session_key"]),
        }
        payload = {key: value}
        response = requests.post(url, data=payload, headers=headers, verify=False)
        if response.status_code != 200:
            self._logger.warn(
                "Failed to update the migration flag for input: {}".format(
                    self._task_config["stanza_name"]
                )
            )

    def send_notification(self, name: str, message: str) -> None:
        """Sends the notification to Splunk UI.

        Args:
            name (str): Name of the message
            message (str): Value of the message
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
        if response.status_code != 201:
            self._logger.warn(
                "Failed to send UI notification for input {}".format(
                    self._task_config["stanza_name"]
                )
            )

    def _sweep_file_checkpoint(self):
        """
        This function is used to delete the checkpoint files after kvstore migration has been completed.
        """
        total_count = 0
        try:
            dir_list = os.scandir(self.checkpoint_dir)
            for ckpt in dir_list:
                try:
                    file_path = self.checkpoint_dir + "/" + ckpt.name
                    os.remove(file_path)
                    total_count = total_count + 1
                    if total_count == 100000:
                        self._logger.debug(
                            "Deleted 100k files from the file checkpoint directory!"
                        )
                        total_count = 0
                except OSError as ex:
                    self._logger.warning(
                        "Failed to delete stale checkpoint file: {} error; {}".format(
                            file_path, ex
                        )
                    )
            if not len(os.listdir(self.checkpoint_dir)):
                self._logger.info("Checkpoint files deleted successfully")
                os.rmdir(self.checkpoint_dir)

        except Exception as e:
            self._logger.warning(
                "An error accoured while deleting the file checkpoint {}".format(e)
            )

    def _get_migration_status(self):
        """
        Used to get the status of migration flag.
        """
        inputs_conf_info = get_conf_file_info(
            self._meta_config.get("session_key"), "inputs"
        )
        stanza_name = "mscs_storage_blob://" + self._task_config["stanza_name"]
        return inputs_conf_info.get(stanza_name, {}).get("is_migrated", "0")

    def _do_batch_checkpoint(self, batch_checkpoint):
        """
        Do batch call to update the checkpoint
        :param batch_checkpoint: dict of various checkpoint with key and value
        """
        if not batch_checkpoint:
            return
        ckpt_list = list(batch_checkpoint.values())
        self._checkpointer.batch_save(ckpt_list)
        batch_checkpoint.clear()

    def collect_data(self):
        batch_checkpoint = {}
        try:
            global_settings = self._all_conf_contents.get(mscs_consts.GLOBAL_SETTINGS)
            sweep_ckpt = global_settings.get("advanced", {}).get(
                "delete_storageblob_ckpt_files", "0"
            )

            if (
                sweep_ckpt == "1"
                and self._task_config["is_migrated"] == "1"
                and os.path.exists(self.checkpoint_dir)
            ):
                thread = threading.Thread(
                    target=self._sweep_file_checkpoint, daemon=True
                )
                thread.start()

            self._logger.info("Starting to collect data.")
            self._storage_dispatcher.start()

            self._logger.debug("Starting to get data from data_writer.")

            limits_conf = get_conf_file_info(
                self._meta_config.get("session_key"), "limits"
            )
            batch_limit = int(
                limits_conf.get("kvstore", {}).get("max_documents_per_batch_save", 1000)
            )

            need_get_data = False
            # When we received the stop signal or the table_dispatcher thread is terminated,
            # we will break the loop.
            self.flush_time = time.time() + self.BATCH_FLUSH_TIMEOUT
            while True:
                try:
                    events, key, ckpt = self._data_writer.get_data(timeout=self.TIMEOUT)
                    stop = yield events, None
                    if not stop and key:
                        batch_checkpoint[key] = self._checkpointer.get_formatted_record(
                            key, ckpt
                        )

                        if (
                            len(batch_checkpoint) >= batch_limit
                            or self.flush_time < time.time()
                        ):
                            self._do_batch_checkpoint(batch_checkpoint)
                            self.flush_time = time.time() + self.BATCH_FLUSH_TIMEOUT
                    if stop:
                        self._storage_dispatcher.cancel()
                        break

                    if not self._storage_dispatcher.is_alive():
                        need_get_data = True
                        break
                except queue.Empty:
                    if not self._storage_dispatcher.is_alive():
                        need_get_data = True
                        break
                    else:
                        self._do_batch_checkpoint(batch_checkpoint)
                        continue

            self._do_batch_checkpoint(batch_checkpoint)

            if not need_get_data:
                self._checkpointer.close()
                return

            self._logger.debug("Retrieve the remaining data from data_writer.")

            while True:
                try:
                    events, key, ckpt = self._data_writer.get_data(block=False)
                    yield events, None
                    if key:
                        batch_checkpoint[key] = self._checkpointer.get_formatted_record(
                            key, ckpt
                        )

                        if len(batch_checkpoint) >= batch_limit:
                            self._do_batch_checkpoint(batch_checkpoint)
                except queue.Empty:
                    break

            self._do_batch_checkpoint(batch_checkpoint)

            self._checkpointer.close()
        except Exception:
            self._do_batch_checkpoint(batch_checkpoint)
            self._logger.exception("Error occurred in collecting data.")
            try:
                self._checkpointer.close()
            except Exception:
                self._logger.exception("Closing checkpointer failed")
            self._storage_dispatcher.cancel()

        if self._task_config["is_migrated"] == "0":
            self._logger.info("Checkpoint has been migrated to KVstore.")
            self.update_migration_flag("is_migrated", "1")
            self.send_notification(
                f"Migration Completed for input {self._task_config['stanza_name']} {time.time()}.",
                "Splunk Add-on for Microsoft Cloud Services: Checkpoint for {} input is now migrated to KV Store.".format(
                    self._task_config["stanza_name"]
                ),
            )

    def _get_task_info(self):
        self._table_list = self._task_config.get(mscs_consts.TABLE_LIST)

    def _get_logger_prefix(self):
        account_stanza_name = self._task_config[mscs_consts.ACCOUNT]
        account_info = self._all_conf_contents[mscs_consts.ACCOUNTS][
            account_stanza_name
        ]
        account_name = account_info.get(mscs_consts.ACCOUNT_NAME)
        pairs = [
            '{}="{}"'.format(
                mscs_consts.STANZA_NAME, self._task_config[mscs_consts.STANZA_NAME]
            ),
            '{}="{}"'.format(mscs_consts.ACCOUNT_NAME, account_name),
            '{}="{}"'.format(
                mscs_consts.CONTAINER_NAME,
                self._task_config[mscs_consts.CONTAINER_NAME],
            ),
            '{}="{}"'.format(
                mscs_consts.BLOB_LIST, self._task_config.get(mscs_consts.BLOB_LIST)
            ),
        ]
        return "[{}]".format(" ".join(pairs))

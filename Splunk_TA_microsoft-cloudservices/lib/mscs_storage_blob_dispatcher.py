#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import copy
import json
import re
import threading
import time
import random
import glob
import os
import traceback
from datetime import datetime, timedelta
import hashlib
from mscs_checkpointer import FileCheckpointer

import mscs_checkpoint_util as cutil
import mscs_consts
import mscs_storage_blob_data_collector as msbdc
import mscs_storage_dispatcher as msd
import mscs_storage_service as mss
import solnlib.utils as utils  # pylint: disable=import-error

from mscs_storage_dispatcher import BlobKeyError, BlobKeyBusy


BLOCK_TIME = 21600
PAGE_SIZE = 5000


class StorageBlobDispatcher(msd.StorageDispatcher):
    def __init__(
        self, all_conf_contents, meta_config, task_config, data_writer, logger
    ):
        super(StorageBlobDispatcher, self).__init__(
            all_conf_contents, meta_config, task_config, data_writer, logger, True
        )
        self._container_name = self._task_config[mscs_consts.CONTAINER_NAME]
        self._include_snapshots = utils.is_true(
            self._task_config.get(mscs_consts.INCLUDE_SNAPSHOTS)
        )
        self._snapshots_start_time = self._task_config.get(
            mscs_consts.SNAPSHOTS_START_TIME
        )
        self._snapshots_end_time = self._task_config.get(mscs_consts.SNAPSHOTS_END_TIME)
        self._storage_service = mss.BlobStorageService(
            all_conf_contents, meta_config, task_config
        )

        self._checkpoint_dir, _ = self._get_checkpoint_dir()
        if self._task_config["is_migrated"] == "0":
            self._file_checkpointer = FileCheckpointer(self._checkpoint_dir)

    def _get_patterns(self):
        blob_list_str = self._task_config.get(mscs_consts.BLOB_LIST)
        if blob_list_str is None or not blob_list_str.strip():
            patterns = {".*": 3}
        else:
            patterns = self._get_blob_patterns(blob_list_str)
        self._logger.debug("The patterns = %s", patterns)
        return patterns

    def _get_application_insights(self):
        application_insights = self._task_config.get(mscs_consts.APPLICATION_INSIGHTS)
        self._logger.info(
            "The application insights checkbox value is = %s", application_insights
        )
        return str(application_insights)

    def _get_application_log_prefixes(self):
        log_type = self._task_config.get(mscs_consts.LOG_TYPE)
        guids = self._task_config.get(mscs_consts.GUIDS)
        self._logger.debug("The log type = %s, The GUIDS are = %s" % (log_type, guids))
        prefixes = []
        if guids and log_type:
            data = guids.split(",")
            for guid in data:
                prefix = guid + "/" + log_type
                prefixes.append(prefix)
        return prefixes

    def _get_exclude_patterns(self):
        exclude_blob_list_str = self._task_config.get(mscs_consts.EXCLUDE_BLOB_LIST)
        if exclude_blob_list_str is None or not exclude_blob_list_str.strip():
            exclude_patterns = {}
        else:
            exclude_patterns = self._get_blob_patterns(exclude_blob_list_str)
        self._logger.debug("The exclude patterns = %s", exclude_patterns)
        return exclude_patterns

    def _get_blob_patterns(self, blob_list_str):
        if not blob_list_str:
            return {}
        try:
            pattern_dct = json.loads(blob_list_str)
        except ValueError:
            blob_pattern_lst = [
                blob.strip() for blob in blob_list_str.split(",") if len(blob.strip())
            ]
            pattern_dct = {}
            for blob_pattern in blob_pattern_lst:
                if blob_pattern.find("*") != -1:
                    pattern_dct[blob_pattern] = 2
                else:
                    pattern_dct[blob_pattern] = 1

        processed_pattern_dct = {}
        for k, v in pattern_dct.items():
            if v == 1:
                processed_pattern_dct[k] = v
            else:
                if v == 2:
                    k2 = k.replace("*", ".*") + "$"
                else:
                    k2 = k + "$"
                try:
                    re.compile(k2)
                except re.sre_compile.error as e:
                    self._logger.warning("%s, blob=%s is invalid.", str(e), k)
                    continue
                processed_pattern_dct[k2] = 3
        return processed_pattern_dct

    def _gen_prefixes(self):
        application_insights = self._get_application_insights()
        app_log_prefixes = self._get_application_log_prefixes()
        prefix_list = []
        # Get the prefix from the UI
        prefix = self._task_config.get(mscs_consts.PREFIX)
        if prefix:
            prefix_list.append(prefix)

        if application_insights == "1":
            self._logger.debug(
                "Application insights is 1. App log prefixes are : %s", app_log_prefixes
            )
            now = datetime.utcnow()
            current_time = now.strftime("%Y-%m-%d/%H")
            before_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d/%H")
            for app_log_prefix in app_log_prefixes:
                current_prefix = app_log_prefix + "/" + current_time
                before_prefix = app_log_prefix + "/" + before_time
                prefix_list.extend([current_prefix, before_prefix])

        if not prefix_list:
            prefix_list.append(None)

        self._logger.debug("All provided prefixes are : %s", prefix_list)
        return prefix_list

    def _confirm_checkpoint_lock(self, ckpt, storage_info):
        """
        _confirm_checkpoint_lock

        double checks if the key in kv store is still locked by
        this process.

        Arguments:
            ckpt
            storage_info


        Raises:
            msd.BlobKeyBusy: if already used by other process
        """
        checkpoint_name = cutil.get_blob_checkpoint_name(
            self._container_name, storage_info["blob_name"], storage_info["snapshot"]
        )
        ckpt2 = self._checkpointer.get(checkpoint_name)
        self._logger.debug(
            "confirming lock and lock_id for blob={}, current_ckpt={} confirm_ckpt={}".format(
                storage_info["blob_name"], ckpt, ckpt2
            )
        )
        if ckpt2 == None:
            self._logger.debug(
                "Couldn't find blob={} while confirming lock, blob will be collected in next interval".format(
                    storage_info["blob_name"]
                )
            )
        elif ckpt2["lock_id"] != ckpt["lock_id"]:
            raise BlobKeyBusy(storage_info["blob_name"])

    def _get_shuffled_buffer(self, blob_list, buffer_size):
        """
        shuffling with a buffer lowers the chances of checkpoint lock clashes
        """
        buffer = []
        for blob in blob_list:
            buffer.append(blob)
            if len(buffer) >= buffer_size:
                random.shuffle(buffer)
                for b in buffer:
                    yield b
                buffer = []

        random.shuffle(buffer)
        for b in buffer:
            yield b

    def _perform_ckpt_migration(self, storage_info):
        """This function is used to perform checkpoint migration from file to kvstore.

        Args:
            storage_info (dict): information of the blob

        Returns:
            dict: if file checkpoint exists for the blob
            None: if file checkpoint does not exists for the blob
        """

        checkpoint_name, key = self._get_checkpoint_name_and_key(storage_info)
        file_path = str(self._checkpoint_dir) + "/" + str(key)
        if os.path.exists(file_path):
            file_ckpt = self._file_checkpointer._do_get(checkpoint_name)
            ckpt = file_ckpt.get("data") if file_ckpt else {}
            if ckpt:
                self._logger.debug(
                    "Found the checkpoint from file for the blob {}".format(
                        storage_info["name"]
                    )
                )
            return ckpt
        else:
            return {}

    def _get_checkpoint_name_and_key(self, storage_info):
        checkpoint_name = cutil.get_blob_checkpoint_name(
            self._container_name,
            storage_info["name"],
            storage_info["snapshot"],
        )
        key = self._checkpointer.format_key(checkpoint_name)
        return checkpoint_name, key

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

    def _cancel_dispatch(self, sub_task_config_list):
        """
        Cancel dispatching and update the checkpoint lock to 0 for the blobs which acquired lock
        :param sub_task_config_list: list of sub task config
        """
        batch_checkpoint = {}
        for stc in sub_task_config_list:
            ckpt_key = cutil.get_blob_checkpoint_name(
                self._container_name, stc["blob_name"], stc["snapshot"]
            )
            checkpoint = self._checkpointer.get(ckpt_key) or {}
            if not checkpoint:
                continue
            checkpoint["lock"] = 0
            batch_checkpoint[ckpt_key] = self._checkpointer.get_formatted_record(
                ckpt_key, checkpoint
            )
        self._do_batch_checkpoint(batch_checkpoint)

    def _dispatch_tasks(self, patterns):
        # sleep so that on start inputs do not try to read same file at the same time
        # this is only a problem is there is only one or two files in the containor
        time.sleep(random.randint(1, 10))

        for prefix in self._gen_prefixes():
            # storage_name_set = set()
            try:
                storage_info_lst = self._get_storage_info_list(patterns, prefix)

            except Exception as e:
                self._logger.error("The number of qualified blobs is %s", str(e))

            task_futures = []
            sub_task_config_list = []
            process_blob_count = 0

            for storage_info in self._get_shuffled_buffer(storage_info_lst, PAGE_SIZE):
                try:
                    ckpt = self._get_ckpt(storage_info.name, storage_info.snapshot)
                    file_ckpt = None
                    if not ckpt and self._task_config["is_migrated"] == "0":
                        ckpt = self._perform_ckpt_migration(storage_info)
                        file_ckpt = ckpt

                    sub_task_config = self._get_sub_task_config(storage_info, ckpt)
                    if not sub_task_config:
                        if self._task_config["is_migrated"] == "0":
                            checkpoint_name, key = self._get_checkpoint_name_and_key(
                                storage_info
                            )
                            self._data_writer.write_ckpt(checkpoint_name, ckpt)
                        continue
                    else:
                        process_blob_count += 1
                        sub_task_config["file_ckpt"] = file_ckpt
                        sub_task_config_list.append(sub_task_config)
                except BlobKeyError as e:
                    self._logger.warning(
                        "Unsupported blob name, it contains some non-ASCII characters blob=%s",
                        e.blob_name,
                    )
                    continue
                except BlobKeyBusy as e:
                    self._logger.warning(
                        "Blob busy with other input - blob=%s",
                        e.blob_name,
                    )
                    continue
                except Exception as e:
                    self._logger.warning(
                        "Blob with unknown checkpoint exception - blob=%s",
                        storage_info.name,
                    )
                    continue

                # confirm ckpt lock after updating ckpt for 100 blobs
                # As KV Store does not have "read after write" consistency but offers eventual consistency
                if len(sub_task_config_list) < mscs_consts.CHUNK_SIZE:
                    continue

                # Retrive the ckpt and add lock
                process_blobs = []
                for stc in sub_task_config_list:
                    blob_info = self._get_and_lock_ckpt(stc)
                    if blob_info:
                        process_blobs.append(blob_info)

                    if self._canceled.is_set():
                        return

                for p_blob in process_blobs:
                    task_future = self._dispatch(
                        p_blob["ckpt"], p_blob["sub_task_config"]
                    )
                    if not task_future:
                        continue
                    task_futures.append(task_future)
                    task_futures = self._wait_while_full(
                        task_futures, self._worker_threads_num
                    )
                    if self._canceled.is_set():
                        self._cancel_dispatch(sub_task_config_list)

                    if self._cancel_sub_tasks(self._canceled):
                        return
                sub_task_config_list = []

            if len(sub_task_config_list):
                if process_blob_count < mscs_consts.CHUNK_SIZE:
                    self._logger.debug("Processing blobs without chunking")
                    is_no_chunking = True

                    for sub_task_config in sub_task_config_list:
                        blob_info = self._get_and_lock_ckpt(sub_task_config)

                        if not blob_info:
                            continue

                        task_future = self._dispatch(
                            blob_info["ckpt"], sub_task_config, is_no_chunking
                        )
                        if not task_future:
                            continue
                        task_futures.append(task_future)
                        task_futures = self._wait_while_full(
                            task_futures, self._worker_threads_num
                        )
                        if self._canceled.is_set():
                            self._cancel_dispatch(sub_task_config_list)

                        if self._cancel_sub_tasks(self._canceled):
                            return
                else:
                    process_blobs = []
                    for stc in sub_task_config_list:
                        blob_info = self._get_and_lock_ckpt(stc)
                        if blob_info:
                            process_blobs.append(blob_info)

                        if self._canceled.is_set():
                            return

                    for p_blob in process_blobs:
                        task_future = self._dispatch(
                            p_blob["ckpt"], p_blob["sub_task_config"]
                        )
                        if not task_future:
                            continue
                        task_futures.append(task_future)
                        task_futures = self._wait_while_full(
                            task_futures, self._worker_threads_num
                        )
                        if self._canceled.is_set():
                            self._cancel_dispatch(sub_task_config_list)

                        if self._cancel_sub_tasks(self._canceled):
                            return

            sub_task_config_list = []

            self._wait_fs(task_futures)
        self._executor.shutdown()

    def _dispatch(self, ckpt, sub_task_config, is_no_chunking=False):
        """
        Dispatch the task to collect the data for the blob
        :param ckpt: checkpoint details
        :param sub_task_config: blob details
        """
        try:
            # check to see if any other process locked the key
            # this can happen when writing at same time to kvstore
            self._confirm_checkpoint_lock(ckpt, sub_task_config)
        except BlobKeyBusy:
            self._logger.warning(
                "Blob busy with other input - blob=%s",
                sub_task_config["blob_name"],
            )
            return None
        except Exception as e:
            self._logger.warning(
                "Blob with unknown checkpoint exception - blob=%s",
                sub_task_config["blob_name"],
            )
            self._logger.warning(
                "Error {}, Blob with unknown checkpoint exception - blob={}, traceback: {}".format(
                    e, sub_task_config["blob_name"], traceback.format_exc()
                )
            )
            return None
        running_task = self._get_running_task()

        task_future = self._executor.submit(
            running_task,
            self._all_conf_contents,
            self._meta_config,
            sub_task_config,
            ckpt,
            self._canceled,
            self._data_writer,
            self._logger,
            is_no_chunking,
            self._confirm_checkpoint_lock,
        )
        return task_future

    def _get_storage_info_list(self, patterns, prefix=None):
        """
        Returns the qualified blob iterator for the blobs under the specified container.
        :param str patterns:
            Indicates the patterns for the data in the blob container.
        :param str prefix:
            Filters the results to return only blobs whose names
            begin with the specified prefix.
        """

        container_client = self._storage_service.get_container_client(self._logger)
        # If snapshots are included in the StorageDispatcher. or go to else construct
        if self._include_snapshots:
            blobs = container_client.list_blobs(
                include=mscs_consts.SNAPSHOT,
                name_starts_with=prefix,
                results_per_page=PAGE_SIZE,
            )
        else:
            blobs = container_client.list_blobs(
                name_starts_with=prefix, results_per_page=PAGE_SIZE
            )

        return self.blob_generator(blobs, patterns)

    # src_blob_lst = [blob for blob in blobs]

    def blob_generator(self, blobs, patterns):
        # self._logger.debug(
        #     "The number of blobs in container %s is %d",
        #     str(self._container_name),
        #     len(src_blob_lst),
        # )

        exclude_patterns = self._get_exclude_patterns()
        # Appending the blobs to blob_list based on what is_match() returns with patterns
        for blob in blobs:
            if self._is_match(
                blob, patterns, self._snapshots_start_time, self._snapshots_end_time
            ) and not self._is_match(
                blob,
                exclude_patterns,
                self._snapshots_start_time,
                self._snapshots_end_time,
            ):
                yield blob

    def _get_and_lock_ckpt(self, sub_task_config):
        """Used to get a checkpoint from kv store and confirm the lock with latest details.

        Args:
            sub_task_config (dict): blob information

        Raises:
            BlobKeyError: raised if blob key error
            BlobKeyBusy: raised if blob is busy

        Returns:
            dict: dictionary of latest checkpoint details and sub_task_config
        """
        process_blob = {}
        try:
            latest_ckpt = None
            if sub_task_config.get("file_ckpt"):
                latest_ckpt = sub_task_config.get("file_ckpt")
            else:
                # get latest checkpoint details to confirm the lock
                latest_ckpt = self._get_ckpt(
                    sub_task_config[mscs_consts.BLOB_NAME],
                    sub_task_config[mscs_consts.SNAPSHOT],
                )

            if not self._is_process_blob(
                latest_ckpt, sub_task_config[mscs_consts.LAST_MODIFIED]
            ):
                return None

            self._lock_ckpt(
                latest_ckpt,
                sub_task_config[mscs_consts.BLOB_NAME],
                sub_task_config[mscs_consts.SNAPSHOT],
            )
            process_blob["ckpt"] = latest_ckpt
            process_blob["sub_task_config"] = sub_task_config
        except BlobKeyError as e:
            self._logger.warning(
                "Unsupported blob name, it contains some non-ASCII characters blob=%s",
                sub_task_config[mscs_consts.BLOB_NAME],
            )
        except BlobKeyBusy:
            self._logger.warning(
                "Blob busy with other input - blob=%s",
                sub_task_config[mscs_consts.BLOB_NAME],
            )
        except Exception as e:
            self._logger.warning(
                "Blob with unknown checkpoint exception - blob=%s",
                sub_task_config[mscs_consts.BLOB_NAME],
            )

        return process_blob

    def _get_ckpt(self, blob_name, snapshot):
        """Used to get a checkpoint from kv store.

        Args:
            storage_info (dict): blob information

        Raises:
            msd.BlobKeyError: raised if blob key error

        Returns:
            dict: checkpoint dictionary from kv store
        """
        try:
            checkpoint_name = cutil.get_blob_checkpoint_name(
                self._container_name, blob_name, snapshot
            )
            ckpt = self._checkpointer.get(checkpoint_name) or {}
            return ckpt
        except KeyError:
            raise msd.BlobKeyError(checkpoint_name)

    def _lock_ckpt(self, ckpt, blob_name, snapshot):
        """Used to lock the checkpoint and update it into kv store.

        Args:
            ckpt (dict): checkpoint dictionary
            storage_info (dict): latest information of the received blob

        """

        try:
            if ckpt.get("lock", 0) > time.time():
                raise BlobKeyBusy(blob_name)

            checkpoint_name = cutil.get_blob_checkpoint_name(
                self._container_name, blob_name, snapshot
            )
            ckpt["lock"] = time.time() + BLOCK_TIME
            ckpt["lock_id"] = random.randint(1000, 99999999999)
            self._checkpointer.update(checkpoint_name, ckpt)
            self._logger.debug(
                "checkpoint lock={} and lock_id={} updated for blob={}".format(
                    ckpt["lock"], ckpt["lock_id"], blob_name
                )
            )
        except KeyError:
            raise msd.BlobKeyError(checkpoint_name)

    def _is_process_blob(self, ckpt, blob_last_modified):
        ckpt = ckpt if ckpt else {}
        is_completed = utils.is_true(ckpt.get(mscs_consts.IS_COMPLETED))
        last_modified = ckpt.get(mscs_consts.LAST_MODIFIED)
        if is_completed and last_modified and last_modified == blob_last_modified:
            return False
        return True

    def _get_sub_task_config(self, storage_info, ckpt):
        if not self._is_process_blob(ckpt, storage_info.last_modified.isoformat("T")):
            return None
        sub_task_config = copy.copy(self._task_config)
        sub_task_config[mscs_consts.BLOB_NAME] = storage_info.name
        sub_task_config[mscs_consts.SNAPSHOT] = storage_info.snapshot
        sub_task_config[mscs_consts.BLOB_TYPE] = storage_info.blob_type
        sub_task_config[mscs_consts.ETAG] = storage_info.etag
        sub_task_config[
            mscs_consts.LAST_MODIFIED
        ] = storage_info.last_modified.isoformat("T")
        sub_task_config[
            mscs_consts.BLOB_CREATION_TIME
        ] = storage_info.creation_time.isoformat("T")
        return sub_task_config

    def _get_running_task(self):
        return msbdc.running_task

    def _union_storage_name_set(self, storage_name_set, storage_info_lst):
        storage_name_lst = [storage_info.name for storage_info in storage_info_lst]
        return storage_name_set.union(storage_name_lst)

    @classmethod
    def _is_match(
        cls, storage_info, pattern_dct, snapshots_start_time, snapshots_end_time
    ):
        if storage_info.snapshot:
            if snapshots_start_time and storage_info.snapshot < snapshots_start_time:
                return False
            if snapshots_end_time and storage_info.snapshot > snapshots_end_time:
                return False
        for k, v in pattern_dct.items():
            if v == 1:
                if storage_info.name == k:
                    return True
            elif v == 3:
                if re.match(k, storage_info.name):
                    return True
        return False

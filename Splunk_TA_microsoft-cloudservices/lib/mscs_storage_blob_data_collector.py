#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import codecs
import sys
import time

import mscs_checkpoint_util as cutil
import mscs_consts
import mscs_logger as logger
import mscs_storage_service as mss
import mscs_util as util
import mscs_storage_dispatcher as msd
import splunktaucclib.common.log as stulog  # pylint: disable=import-error
import splunktaucclib.data_collection.ta_data_client as dc  # pylint: disable=import-error


def running_task(
    all_conf_contents,
    meta_config,
    task_config,
    ckpt,
    canceled,
    data_writer,
    logger_prefix,
    is_no_chunking,
    confirm_checkpoint_lock,
):
    try:
        data_collector = StorageBlobDataCollector(
            all_conf_contents,
            meta_config,
            task_config,
            ckpt,
            canceled,
            data_writer,
            is_no_chunking,
            confirm_checkpoint_lock,
        )

        data_collector.collect_data()
    except Exception as e:
        stulog.logger.exception(
            "%s Exception@running_task(), error_message=%s", logger_prefix, str(e)
        )


class StorageBlobDataCollector(mss.BlobStorageService):
    BLOCK_TIME = 300
    DEFAULT_BATCH_SIZE = 8192

    DEFAULT_DECODING = "utf-8"

    def __init__(
        self,
        all_conf_contents,
        meta_config,
        task_config,
        ckpt,
        canceled,
        data_writer,
        is_no_chunking,
        confirm_checkpoint_lock,
    ):
        super(StorageBlobDataCollector, self).__init__(
            all_conf_contents, meta_config, task_config
        )

        self._ckpt = ckpt if ckpt else {}
        self._canceled = canceled
        self._data_writer = data_writer
        self._container_name = None
        # assign by blob dispathcer
        self._blob_name = None
        self._snapshot = None
        self._blob_type = None
        self._last_modified = None
        self._blob_creation_time = None
        self._blob_mode = None
        self._index = None
        self._sourcetype = None
        self._batch_size = None
        self._etag = None
        # init self._decoder
        self._decoder = None
        self._logger = logger.logger_for(self._get_logger_prefix())

        self._is_no_chunking = is_no_chunking
        # wrapper to confirm the lock
        self._confirm_checkpoint_lock = confirm_checkpoint_lock

        self._get_task_info()
        self._ckpt_name = cutil.get_blob_checkpoint_name(
            self._container_name, self._blob_name, self._snapshot
        )

    def collect_data(self):
        # check whether any other input locked the blob this can happen because
        # KV Store does not have "read after write" consistency but offers eventual consistency
        if self._is_no_chunking:
            time.sleep(1)
            # lock aquired by another input then return
            if not self._confirm_ckpt_lock():
                return

        try:
            self._logger.debug(
                "Starting to collect data for blob={}".format(self._blob_name)
            )
            self._do_collect_data()
            self._logger.debug(
                "Finish collecting data for blob={}".format(self._blob_name)
            )
        except Exception:
            self._logger.exception("Error occurred in collecting data")

    def _confirm_ckpt_lock(self):
        """Confirm checkpoint lock
        Double checks if the key in kv store is still locked by
        this process.

        Raises:
            msd.BlobKeyBusy: if already used by other process
        """
        try:
            self._confirm_checkpoint_lock(self._ckpt, self._task_config)
        except msd.BlobKeyBusy:
            self._logger.warning(
                "Blob busy with other input - blob=%s",
                self._task_config[mscs_consts.BLOB_NAME],
            )
            return False
        except Exception as e:
            self._logger.warning(
                "Blob with unknown checkpoint exception - blob=%s",
                self._task_config[mscs_consts.BLOB_NAME],
            )
            return False

        return True

    def _do_collect_data(self):
        self._logger.debug(
            "Starting to process checkpoint for blob={}".format(self._blob_name)
        )
        self._process_ckpt()
        self._logger.debug(
            "Finishing process checkpoint for blob={}".format(self._blob_name)
        )

        # check the canceled flag
        if self._canceled.is_set():
            return

        # get blob service
        blob_client = self.get_blob_client(self._logger, self._blob_name)
        while not self._canceled.is_set():
            self._logger.debug(
                "blob: %s blob_mode: %s blob_type: %s",
                str(self._blob_name),
                str(self._blob_mode),
                str(self._blob_type),
            )
            append_mode = (
                self._blob_mode == mss.BlobModeType.APPEND
                or self._blob_type == mss.BlobType.APPEND_BLOB
            )
            self._logger.debug("append_mode: %s", str(append_mode))
            first_process_blob, received_bytes, blob = self._dc_get_blob(
                append_mode, blob_client
            )

            if blob is None:
                self._logger.info("get_blob returned None")
                break

            is_finished = False
            blob_len = self._get_blob_len(blob)
            blob_content = blob.readall()
            self._logger.debug(
                "blob: %s received_bytes: %s blob_len: %s len(blob_content): %s",
                str(self._blob_name),
                str(received_bytes),
                str(blob_len),
                str(len(blob_content)),
            )

            if received_bytes + len(blob_content) >= blob_len:
                is_finished = True

            # get decoded blob contents
            content = self._get_blob_content(first_process_blob, blob)

            self._ckpt[
                mscs_consts.LAST_MODIFIED
            ] = blob.properties.last_modified.isoformat("T")
            self._ckpt[mscs_consts.BLOB_CREATION_TIME] = self._blob_creation_time

            if is_finished:
                self._ckpt[mscs_consts.IS_COMPLETED] = 1
                self._ckpt["lock"] = 0
            else:
                self._ckpt["lock"] = time.time() + self.BLOCK_TIME

            self._ckpt[mscs_consts.RECEIVED_BYTES] += len(blob_content)
            self._logger.debug(
                "blob: %s Checkpointed Bytes %s",
                str(self._blob_name),
                str(self._ckpt[mscs_consts.RECEIVED_BYTES]),
            )

            # if lock aquired by another input in between data processing then return
            if not self._confirm_ckpt_lock():
                self._logger.debug(
                    "Lock aquired by another input in between processing the blob: %s",
                    str(self._blob_name),
                )
                break

            if content:
                self._logger.debug(
                    "Successfully decoded blob contents for blob={}".format(
                        self._blob_name
                    )
                )
                event = self._build_event(content, is_finished)
                self._data_writer.write_events_and_ckpt(
                    [event], self._ckpt_name, self._ckpt
                )
            else:
                self._logger.debug("Blob contents not decoded")
                self._data_writer.write_ckpt(self._ckpt_name, self._ckpt)

            if is_finished:
                break

    def _get_append_blob(self, blob_client):
        first_process_blob, blob_stream_downloader = False, None

        if self._blob_creation_time != self._ckpt.get(mscs_consts.BLOB_CREATION_TIME):
            self._logger.debug(
                f"BLOB_CREATION_TIME is different reseting RECEIVED_BYTES to 0"
            )
            self._ckpt[mscs_consts.RECEIVED_BYTES] = 0

        received_bytes = self._ckpt.get(mscs_consts.RECEIVED_BYTES)

        if not received_bytes:
            first_process_blob = True

        try:
            self._logger.debug(
                "start_range: %s end_range: %s",
                str(received_bytes),
                str(received_bytes + self._batch_size - 1),
            )
            blob_stream_downloader = blob_client.download_blob(
                snapshot=self._snapshot,
                offset=received_bytes,
                length=self._batch_size,
            )

        except Exception as e:
            if e.error_code == "InvalidRange":  # pylint: disable=no-member
                blob_stream_downloader = blob_client.download_blob(
                    snapshot=self._snapshot
                )
                blob_content = blob_stream_downloader.readall()

                self._logger.warning(
                    "Invalid Range Error: Bytes stored in Checkpoint : "
                    + str(received_bytes)
                    + " and Bytes stored in "
                    + str(self._blob_name)
                    + " : "
                    + str(len(blob_content))
                    + ". Restarting the data collection for "
                    + str(self._blob_name)
                )
                first_process_blob = True
                self._ckpt[mscs_consts.RECEIVED_BYTES] = 0
                received_bytes = 0
            else:
                # invalid range error, etag mismatching, file not found, or server failure
                self._logger.exception(
                    "Failed to collect the blob %s due to exception : %s",
                    str(self._blob_name),
                    str(e.error_code),  # pylint: disable=no-member
                )

        return first_process_blob, received_bytes, blob_stream_downloader

    def _get_entire_blob(self, blob_client):
        self._logger.debug(
            "Starting data collection for blob type %s", str(self._blob_type)
        )
        # This phase will always retrive full blob content
        first_process_blob, received_bytes, blob_stream_downloader = True, 0, None
        self._ckpt[mscs_consts.RECEIVED_BYTES] = 0

        try:
            # matching the etag value of the list_blob to ensure data integrity
            blob_stream_downloader = blob_client.download_blob(
                snapshot=self._snapshot,
                if_match=self._etag,
            )

        except Exception as e:
            # etag mismatching, file not found, or server failure
            self._logger.exception(
                "Failed to collect the blob due to exception : %s",
                str(e.error_code),  # pylint: disable=no-member
            )

        return first_process_blob, received_bytes, blob_stream_downloader

    def _dc_get_blob(self, append_mode, blob_client):
        if append_mode:
            return self._get_append_blob(blob_client)
        return self._get_entire_blob(blob_client)

    def _get_codeset(self, head_data=None):
        # checkpoint
        if self._ckpt.get(mscs_consts.CODESET):
            return self._ckpt[mscs_consts.CODESET]
        # check bom
        if head_data:
            with_bom = util.check_bom(head_data)
            if with_bom:
                return with_bom[0]
            self._logger.debug("Failed to detect the bom header.")
        # conf file
        if self._task_config.get(mscs_consts.DECODING):
            return self._task_config.get(mscs_consts.DECODING)
        # sys default
        if sys.getdefaultencoding():
            return sys.getdefaultencoding()
        return StorageBlobDataCollector.DEFAULT_DECODING

    def _set_decoder(self, first_process_blob, blob):
        if first_process_blob:
            codeset = self._get_codeset(blob.readall())
            self._logger.debug("The codeset=%s", codeset)

            try:
                self._decoder = codecs.getincrementaldecoder(codeset)(errors="replace")
            except LookupError:
                self._logger.error(
                    "charset=%s raise LookupError. " "Charset will be set to utf-8",
                    codeset,
                )
                codeset = StorageBlobDataCollector.DEFAULT_DECODING
                self._decoder = codecs.getincrementaldecoder(codeset)(errors="replace")
            self._ckpt[mscs_consts.CODESET] = codeset
            self._logger.debug("charset=%s", codeset)

        else:
            codeset = self._get_codeset()
            self._logger.debug("The codeset=%s", codeset)
            if not self._decoder:
                self._decoder = codecs.getincrementaldecoder(codeset)(errors="replace")

    def _get_blob_content(self, first_process_blob, blob):
        self._set_decoder(first_process_blob, blob)
        return self._decoder.decode(blob.readall())

    def _get_task_info(self):

        self._container_name = self._task_config[mscs_consts.CONTAINER_NAME]
        self._blob_name = self._task_config[mscs_consts.BLOB_NAME]
        self._snapshot = self._task_config.get(mscs_consts.SNAPSHOT)
        if not self._snapshot:
            self._snapshot = None
        self._blob_type = self._task_config[mscs_consts.BLOB_TYPE]
        self._last_modified = self._task_config[mscs_consts.LAST_MODIFIED]
        self._blob_creation_time = self._task_config[mscs_consts.BLOB_CREATION_TIME]
        self._etag = self._task_config[mscs_consts.ETAG]
        self._blob_mode = self._task_config.get(
            mscs_consts.BLOB_MODE, mss.BlobModeType.RANDOM
        )
        self._logger.debug("The blob_mode=%s", self._blob_mode)

        if (
            self._blob_type == mss.BlobType.APPEND_BLOB
            and self._blob_mode == mss.BlobModeType.RANDOM
        ):
            self._logger.warning(
                "Set blob_mode=random for AppendBlob doesn't have any effect, "
                "this add-on will treat AppendBlob as blob_mode=append"
            )

        self._index = self._task_config[mscs_consts.INDEX]
        self._sourcetype = self._task_config[mscs_consts.SOURCETYPE]
        self._batch_size = int(
            self._all_conf_contents[mscs_consts.GLOBAL_SETTINGS][
                mscs_consts.PERFORMANCE_TUNING_SETTINGS
            ][mscs_consts.GET_BLOB_BATCH_SIZE]
        )
        if self._batch_size <= 1:
            self._logger.warning(
                "%s=%s is invalid, assign %s to query_entities_page_size",
                mscs_consts.GET_BLOB_BATCH_SIZE,
                self._batch_size,
                self.DEFAULT_BATCH_SIZE,
            )

    def _get_logger_prefix(self):
        tconf = self._task_config
        pairs = [
            '{}="{}"'.format(k, v)
            for k, v in [
                (mscs_consts.STANZA_NAME, tconf[mscs_consts.STANZA_NAME]),
                (mscs_consts.ACCOUNT_NAME, self._account_name),
                (mscs_consts.CONTAINER_NAME, tconf[mscs_consts.CONTAINER_NAME]),
                (mscs_consts.BLOB_NAME, tconf[mscs_consts.BLOB_NAME]),
                (mscs_consts.SNAPSHOT, tconf.get(mscs_consts.SNAPSHOT)),
            ]
            if v
        ]

        return "[{}]".format(" ".join(pairs))

    def _process_ckpt(self):

        if not self._ckpt.get(mscs_consts.LAST_MODIFIED):
            self._init_ckpt()
        if (
            self._blob_mode == mss.BlobModeType.APPEND
            or self._blob_type == mss.BlobType.APPEND_BLOB
            or self._snapshot
        ):
            self._ckpt[mscs_consts.IS_COMPLETED] = 0
            self._ckpt[mscs_consts.LAST_MODIFIED] = self._last_modified
            self._ckpt[mscs_consts.BLOB_CREATION_TIME] = self._blob_creation_time
        else:
            ckpt_last_modified = self._ckpt.get(mscs_consts.LAST_MODIFIED)
            if self._last_modified != ckpt_last_modified:
                self._logger.debug(
                    "The last_modified in checkpoint "
                    "is not equal to the last_modified returned by blob_client, "
                    "reinitialize the checkpoint."
                )
                self._init_ckpt()

    def _init_ckpt(self):
        self._ckpt[mscs_consts.RECEIVED_BYTES] = 0
        self._ckpt[mscs_consts.IS_COMPLETED] = 0
        self._ckpt[mscs_consts.LAST_MODIFIED] = self._last_modified
        self._ckpt[mscs_consts.BLOB_CREATION_TIME] = self._blob_creation_time
        self._ckpt[mscs_consts.CODESET] = None

    def _build_event(self, content, is_finished):
        if self._snapshot:
            source = ":".join((self._blob_name, self._snapshot))
        else:
            source = self._blob_name
        is_done = True if is_finished else False
        return dc.build_event(
            source=source,
            sourcetype=self._sourcetype,
            index=self._index,
            raw_data=content,
            is_unbroken=True,
            is_done=is_done,
        )

    @classmethod
    def _get_blob_len(cls, blob):
        if not blob.properties.content_range:
            return 0
        index = blob.properties.content_range.find("/")
        return int(blob.properties.content_range[index + 1 :])  # noqa: E203

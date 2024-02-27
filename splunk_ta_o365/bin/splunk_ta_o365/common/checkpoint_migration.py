#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import os
import requests
from splunk_ta_o365.common.utils import time_taken
from splunksdc import logging
from splunksdc.checkpoint import Partition
from splunk_ta_o365.common.checkpoint import KVStoreCheckpoint, FileBasedCheckpoint


logger = logging.get_module_logger()


class CheckpointMigration:
    def __init__(self, collection, app, config, kind: str, input_name: str) -> None:
        """
        Checkpoint Migration old

        Args:
            collection (_type_): collection object
            app (_type_): app object
            config (_type_): config object
            kind (str): kind of input
            input_name (str): input name
        """
        self._collection = collection
        self._app = app
        self._config = config
        self._kind = kind
        self._input_name = input_name

    def load_checkpoint(self, filename: str) -> None:
        """
        This method used to load the file-based checkpoint

        Args:
            filename (str): filename or input name
        """
        with self._app.open_checkpoint(filename) as fp_checkpoint:
            fp_checkpoint.sweep()
            self.ckpt_data = list(Partition(fp_checkpoint, "/v1/").items())
        logger.info(
            "Successfully loaded the checkpoint for input : {}".format(filename)
        )

    def migrate(self):
        """
        This method used the migrate the checkpoint to KV
        """
        # Create the batch list from the checkpoint data
        batch_list: list = []
        # get the max batch save from limits.conf if specified else default 1000
        max_documents_per_batch_save: int = int(
            self._config._service.confs["limits"]["kvstore"].content.get(
                "max_documents_per_batch_save", 1000
            )
        )
        while self.ckpt_data:
            for key, value in self.ckpt_data[:max_documents_per_batch_save]:
                batch_list.append({"_key": key, "expiration": value})
            self._collection.batch_save(batch_list)
            batch_list.clear()
            del self.ckpt_data[:max_documents_per_batch_save]
        logger.info(
            "Successfully stored the checkpoints in the kv-store collection : {}".format(
                self._collection._collection_name
            )
        )

    def remove_file(self, filename: str) -> None:
        """
        Used to remove the checkpoint file

        :param filename: checkpoint file path.
        :type filename: ``string``
        """
        try:
            os.remove(filename)
            os.remove(filename.replace(".ckpt", ".lock"))
            logger.info(
                "Successfully removed the checkpoint file : {}".format(filename)
            )
        except:
            logger.error("Failed to remove the checkpoint file : {}".format(filename))

    def send_notification(self, name: str, message: str) -> None:
        """
        Used to send the notification splunk UI.

        :param name: message name or key.
        :type input_name: ``string``
        :param message: message value.
        :type input_name: ``string``
        """
        url: str = "{}://{}:{}/services/messages".format(
            self._app._context._server_scheme,
            self._app._context._server_host,
            self._app._context._server_port,
        )
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Bearer {}".format(self._config._service.token),
        }
        payload = {
            "name": name,
            "value": message,
            "severity": "info",
        }
        response = requests.post(url, data=payload, headers=headers, verify=False)
        if response.status_code == 201:
            logger.info("Successfully sent the migration notification.")
        else:
            logger.warn("Failed to send the migration notification.")


class CheckpointMigrationV2:
    def __init__(self, app, config, kind: str, input_name: str) -> None:
        """
        Checkpoint Migration for version 2
        approach for management activitiy inputs

        Args:
            app (_type_): app object
            config (_type_): config object
            kind (str): kind of input
            input_name (str): input name
        """
        self._app = app
        self._config = config
        self._kind = kind
        self._input_name = input_name
        self._checkpoint = None
        self._service = self._config._service

    def _get_kvstore_checkpoint(self) -> bool:
        """
        Load KVStore collection

        Returns:
            bool: collection loaded or not
        """
        collection_name = self._get_kvstore_collection_name()
        # Load the existing kv-store checkpoint
        logger.debug("Loading(KVStore) Older checkpoint", checkpoint=collection_name)
        try:
            self._checkpoint = KVStoreCheckpoint(
                collection_name=collection_name, service=self._service
            )
            self._checkpoint.load_collection()
            return True
        except ValueError as e:
            logger.debug(
                "Unable to load checkpoint(KVStore) info",
                exception=str(e),
            )

        return False

    def _get_kvstore_collection_name(self) -> str:
        """
        Get the checkpoint's collection name

        Returns:
            str: collection name
        """
        collection_name = f"{self._kind}_{self._input_name}"
        return collection_name

    def _get_file_checkpoint_name(self) -> str:
        """
        Get the checkpoint's filename with path

        Returns:
            str: Name of the checkpoint file along with path
        """
        checkpoint_file = os.path.join(
            self._app._context._checkpoint_dir, "{}.ckpt".format(self._input_name)
        )
        return checkpoint_file

    def _get_filebased_checkpoint(self) -> bool:
        """
        Load FileBased checkpoint

        Returns:
            bool: checkpoint file is loaded or not
        """
        checkpoint_file = self._get_file_checkpoint_name()
        logger.debug("Loading(File) Older checkpoint", checkpoint=checkpoint_file)
        if os.path.exists(checkpoint_file):
            try:
                self._checkpoint = FileBasedCheckpoint(checkpoint_file)
                self._checkpoint.load_checkpoint()
                return True
            except Exception as e:
                logger.debug(
                    "Unable to load checkpoint(File) info",
                    exception=str(e),
                )

        return False

    @time_taken(logger, "Time consumed for loading migration checkpoint", False)
    def load_checkpoint(self) -> bool:
        """
        Load checkpoint

        Returns:
            bool: checkpoint is loaded or not
        """
        if self._get_filebased_checkpoint():
            return True
        else:
            return self._get_kvstore_checkpoint()

    def get(self, key: str) -> bool:
        """
        Check if given key exists in
        checkpoint

        Args:
            key (str): unique key to check

        Returns:
            bool: key exists or not
        """
        return self._checkpoint.get(key)

    @time_taken(logger, "Time consumed for deleting migration checkpoint", False)
    def delete(self) -> None:
        """
        Delete the checkpoints info

        Notes:
            Will try to delete both the checkpoint (KVStore collection or file)
            to make sure in odd cases if user have both the checkpoint available.
        """
        logger.info("Deleting Older Checkpoints info.")
        collection_name = self._get_kvstore_collection_name()
        file_checkpoint_name = self._get_file_checkpoint_name()
        KVStoreCheckpoint.delete_collection(self._service.kvstore, collection_name)
        FileBasedCheckpoint.delete(file_checkpoint_name)

    def close(self) -> None:
        """
        Close the file
        """
        if isinstance(self._checkpoint, FileBasedCheckpoint):
            self._checkpoint.close()

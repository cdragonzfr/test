#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import re
import json
import traceback
import time
import os

from functools import wraps
from splunksdc import logging
from splunklib import binding
from typing import Any, List, Dict, Union
from splunksdc.checkpoint import Partition, LocalKVStore


logger = logging.get_module_logger()


def retry(
    retries: int = 3,
    reraise: bool = True,
    default_return: Any = None,
    exceptions: List = None,
    log_exception: bool = True,
):

    """
    A decorator to run function with max `retries` times if there is exception.

    Args:
        retries (int, optional): Max retries times. Default is 3.
        reraise (bool, optional): Whether exception should be reraised.
        default_return (Any, optional): Default return value for function
            run after max retries and reraise is False.
        exceptions (List, optional): List of exceptions that should retry.
        log_exception (bool, optional): Should log the exception or not.

    Returns:
        The decorator function `do_retry` that takes in a function as input
        and returns a wrapped function with retry functionality.
    """
    max_tries = max(retries, 0) + 1

    def do_retry(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_ex = None
            for i in range(max_tries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if log_exception:
                        logger.warning(
                            "Run function: %s failed: %s.",
                            func.__name__,
                            traceback.format_exc(),
                        )
                    if not exceptions or any(
                        isinstance(e, exception) for exception in exceptions
                    ):
                        last_ex = e
                        if i < max_tries - 1:
                            time.sleep(2**i)
                    else:
                        raise
            if reraise:
                raise last_ex
            else:
                return default_return

        return wrapper

    return do_retry


class KVStoreCheckpoint:
    def __init__(self, collection_name: str, service: Any, fields={}) -> None:
        """
        KVStore checkpoint

        Args:
            collection_name (str): name of the collection
            service (Any): service
            fields (dict, optional): field object. Defaults to {}.
        """
        self._collection_name = self.get_valid_name(collection_name)
        self._fields = fields
        self._service = service
        self._kv_store = self._service.kvstore
        self._collection = None

    def create_collection(self) -> None:
        """
        Create the new KVStore Collection
        """
        self._kv_store.create(self._collection_name, fields=self._fields)
        logger.info(
            "Created KVStore Collection Successfully: {}".format(self._collection_name)
        )

    @staticmethod
    def delete_collection(KVStore: Any, collection_name: str) -> None:
        """
        Delete the given collection

        Args:
            KVStore (Any): KVStore instance
            collection_name (str): Name of the collection to be deleted
        """
        collection_name = KVStoreCheckpoint.get_valid_name(collection_name)
        try:
            KVStore.delete(collection_name)
            logger.info(f"Deleted KVStore Collection Successfully: {collection_name}.")
        except KeyError as ke:
            logger.debug(
                "Exception while deleting collection.",
                exception=str(ke),
                collection_name=collection_name,
            )
        except Exception as e:
            logger.error(
                "Exception",
                exception=str(e),
                collection_name=collection_name,
            )

    @staticmethod
    def get_valid_name(name: str) -> str:
        """
        Get the name without spl char [except -> "_"]
            ex  => @coll_name_test_^&*
                => coll_name_test

        Args:
            name (str): user provided name

        Returns:
            str: validated name
        """
        return re.sub(r"[^\w]+", "_", name)

    def _is_collection_available(self) -> bool:
        """
        Check if collection available or not

        Returns:
            bool: if collection found
        """
        if self._collection_name not in self._kv_store:
            return False
        return True

    @retry(exceptions=[binding.HTTPError])
    def get_collection(self) -> None:
        """
        This Method used to load | create the KVStore Collection
        """
        # Create the new collection if not exists
        if not self._is_collection_available():
            self.create_collection()

        self._collection = self._kv_store[self._collection_name].data

    @retry(exceptions=[binding.HTTPError], log_exception=False)
    def load_collection(self) -> None:
        """
        This Method used to load the KVStore Collection
        """
        # Check if collection exists
        if not self._is_collection_available():
            raise ValueError(f"Collection {self._collection_name} not found.")

        self._collection = self._kv_store[self._collection_name].data

    @retry(exceptions=[binding.HTTPError])
    def get(self, checkpoint_key: str) -> Union[Dict, None]:
        """
        Get checkpoint details based on provided key

        Args:
            checkpoint_key (str): unique key

        Returns:
            Union[Dict, None]: checkpoint details
        """
        try:
            data = self._collection.query_by_id(id=checkpoint_key)
        except binding.HTTPError as e:
            if e.status != 404:
                logger.error(
                    "Unable to get checkpoint details",
                    exc_info=True,
                    stack_info=True,
                )
                raise
            return None
        return data

    @retry(exceptions=[binding.HTTPError])
    def save(self, record: Dict) -> None:
        """
        Inserts a single record into this collection. If the record does not
        contain an _key field, it will be generated.

        Args:
            record (Dict): A dictionary containing the record to be inserted.

        Returns:
            None
        """
        self._collection.insert(record)

    @retry(exceptions=[binding.HTTPError])
    def batch_save(self, records: List) -> None:
        """
        Inserts a batch of records into this collection. If a record does not contain
        an _key field, it will be generated.

        Args:
            records (List): A list of dictionaries, each containing a record
                to be inserted.

        Returns:
            None
        """
        self._collection.batch_save(*records)

    @retry(exceptions=[binding.HTTPError])
    def delete(self, query: Dict = None) -> None:
        """
        Deletes one or more records from the collection using the provided query.
        If no query is provided, all records will be deleted.

        Args:
            query (Dict, optional): A dictionary containing the query to use for
                deleting records. Defaults to None.

        Returns:
            None
        """
        if query:
            query = json.dumps(query)
        self._collection.delete(query)

    @retry(exceptions=[binding.HTTPError])
    def delete_by_id(self, id: str = None) -> Any:
        """
        Deletes the record with the provided ID.

        Args:
            id (str, optional): The ID of the record to delete. Defaults to None.

        Returns:
            Any: The result of the DELETE request.
        """
        self._collection.delete_by_id(id)

    @retry(exceptions=[binding.HTTPError])
    def update(self, checkpoint_key: str, checkpoint_data: Union[Dict, str]) -> Dict:
        """
        Replaces the document with the specified checkpoint key with the provided data.

        Args:
            checkpoint_key (str): The checkpoint key of the document to be replaced.
            checkpoint_data (Union[Dict, str]): The new data to replace the existing
            document with.

        Returns:
            Dict: The ID of the replaced document.
        """
        self._collection.update(checkpoint_key, checkpoint_data)


class FileBasedCheckpoint:
    def __init__(self, filename: str) -> None:
        """
        FileBased checkpoint

        Args:
            filename (str): name of the checkpoint file
        """
        self._filename = filename
        self._checkpoint = None
        self._localKVStore = None

    def load_checkpoint(self) -> None:
        """
        Load checkpoint info
        """
        # LocalKVstore obj is for handling fileBased ckpt
        self._localKVStore = LocalKVStore.open_always(self._filename)
        self._localKVStore.sweep()
        self._checkpoint = Partition(self._localKVStore, "/v1/")

    def get(self, key: str) -> bool:
        """
        Find given key present in
        checkpoint info

        Args:
            key (str): unique key

        Returns:
            bool: key found or not
        """
        return self._checkpoint.find(key)

    @staticmethod
    def delete(filename: str) -> None:
        """
        Delete the checkpoint file

        Args:
            filename (str): checkpoint filename to be deleted.
        """
        try:
            os.remove(filename)
            os.remove(filename.replace(".ckpt", ".lock"))
        except FileNotFoundError as fe:
            logger.debug(
                "Exception while deleting the checkpoint file.",
                exception=str(fe),
                filename=filename,
            )
        except Exception as e:
            logger.error(
                "Exception",
                exception=str(e),
                filename=filename,
            )

    def close(self):
        """
        Close the file
        """
        self._localKVStore.close()

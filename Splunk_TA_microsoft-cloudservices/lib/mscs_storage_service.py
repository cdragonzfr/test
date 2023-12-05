#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import abc
from builtins import object

import mscs_consts
from mscs_util import make_proxy_url, proxy_from_config

from azure.core.credentials import (  # isort: skip # pylint: disable=import-error
    AzureNamedKeyCredential,
    AzureSasCredential,
)
from azure.data.tables import (  # isort: skip # pylint: disable=import-error
    TableServiceClient,
)
from azure.storage.blob import (  # isort: skip # pylint: disable=import-error
    BlobServiceClient,
)
from future.utils import with_metaclass  # isort: skip # pylint: disable=import-error


class AccountSecretType(object):
    NONE_SECRET = 0
    ACCESS_KEY = 1
    SAS_TOKEN = 2


class AccountClassType(object):
    STANDARD_ACCOUNT = 1
    GOVCLOUD_ACCOUNT = 2
    CHINA_ACCOUNT = 3
    GERMANY_ACCOUNT = 4


class BlobModeType(object):
    APPEND = "append"
    RANDOM = "random"


class BlobType(object):
    BLOCK_BLOB = "BlockBlob"
    APPEND_BLOB = "AppendBlob"
    PAGE_BLOB = "PageBlob"


def _create_table_service(
    account_name,
    account_secret_type,
    account_secret,
    account_class_type,
    proxies=None,
):

    BASE_TABLE_ACCOUNT_URL = "https://{account_name}.table.{suffix}"
    suffix = return_endpoint_suffix(account_class_type)
    account_url = BASE_TABLE_ACCOUNT_URL.format(
        account_name=account_name, suffix=suffix
    )

    if account_secret_type == AccountSecretType.ACCESS_KEY:
        return TableServiceClient(
            endpoint=account_url,
            credential=AzureNamedKeyCredential(account_name, account_secret),
            proxies=proxies,
        )
    if account_secret_type == AccountSecretType.SAS_TOKEN:
        return TableServiceClient(
            endpoint=account_url,
            credential=AzureSasCredential(account_secret),
            proxies=proxies,
        )
    raise Exception(
        "The account_secret_type={} is unsupported by table service".format(
            account_secret_type
        )
    )


def _create_blob_service(
    account_name,
    account_secret_type,
    account_secret,
    account_class_type,
    proxies=None,
):

    BASE_BLOB_ACCOUNT_URL = "https://{account_name}.blob.{suffix}"
    suffix = return_endpoint_suffix(account_class_type)
    account_url = BASE_BLOB_ACCOUNT_URL.format(account_name=account_name, suffix=suffix)

    if account_secret_type == AccountSecretType.ACCESS_KEY:
        return BlobServiceClient(
            account_url=account_url,
            credential={"account_name": account_name, "account_key": account_secret},
            proxies=proxies,
        )
    elif account_secret_type == AccountSecretType.SAS_TOKEN:
        return BlobServiceClient(
            account_url=account_url, credential=account_secret, proxies=proxies
        )
    elif account_secret_type == AccountSecretType.NONE_SECRET:
        return BlobServiceClient(account_url=account_url, proxies=proxies)

    raise Exception(
        "The account_secret_type={} is unsupported by table service".format(
            account_secret_type
        )
    )


def _get_proxy_dict(proxy_config, logger):
    proxy_as_tuple = proxy_from_config(proxy_config)
    if not proxy_as_tuple:
        logger.info("Proxy is disabled.")
        return None

    logger.info("Proxy is enabled.")

    host, port, user, password = proxy_as_tuple
    proxy_url = make_proxy_url(host=host, port=port, user=user, password=password)

    # Overwriting proxy for https scheme to http (To resolve urllib3 v1.26.5 version update failure)
    logger.info("Changing proxy schemes to http as only http proxy is supported")
    proxy_dict = {"https": proxy_url, "http": proxy_url}
    return proxy_dict


def _get_proxy_config(all_conf):
    global_settings = all_conf.get(mscs_consts.GLOBAL_SETTINGS)
    return global_settings.get(mscs_consts.PROXY) if global_settings else None


class StorageService(with_metaclass(abc.ABCMeta, object)):  # type: ignore
    def __init__(self, all_conf_contents, meta_config, task_config):
        self._all_conf_contents = all_conf_contents
        self._meta_config = meta_config
        self._task_config = task_config
        self._account_name = None
        self._account_secret_type = None
        self._account_class_type = None
        self._account_secret = None
        self._storage_service = None
        self._parse_account_info()
        self._proxy_config = _get_proxy_config(all_conf_contents)

    def get_service(self, logger):
        if not self._storage_service:
            self._storage_service = self._create_service(logger)
        return self._storage_service

    @abc.abstractmethod
    def _create_service(self, logger_prefix):
        pass

    def _parse_account_info(self):
        account_stanza_name = self._task_config[mscs_consts.ACCOUNT]
        account_info = self._all_conf_contents[mscs_consts.ACCOUNTS][
            account_stanza_name
        ]
        self._account_name = account_info[mscs_consts.ACCOUNT_NAME]
        self._account_secret_type = int(account_info[mscs_consts.ACCOUNT_SECRET_TYPE])

        self._validate_account_secret_type()

        try:
            self._account_class_type = int(account_info[mscs_consts.ACCOUNT_CLASS_TYPE])
        except KeyError:
            self._account_class_type = AccountClassType.STANDARD_ACCOUNT

        self._validate_account_class_type()

        if self._account_secret_type == AccountSecretType.ACCESS_KEY:
            self._account_secret = account_info.get(mscs_consts.ACCOUNT_SECRET)
        elif self._account_secret_type == AccountSecretType.SAS_TOKEN:
            self._account_secret = self._process_sas_token(
                account_info.get(mscs_consts.ACCOUNT_SECRET)
            )

    def _validate_account_secret_type(self):
        if self._account_secret_type is None:
            raise Exception("The account_secret_type is None.")
        if self._account_secret_type not in (
            AccountSecretType.NONE_SECRET,
            AccountSecretType.ACCESS_KEY,
            AccountSecretType.SAS_TOKEN,
        ):
            raise Exception(
                "The account_secret_type={} is invalid.".format(
                    self._account_secret_type
                )
            )

    def _validate_account_class_type(self):
        if self._account_class_type is None:
            raise Exception("The account_class_type is None.")
        if self._account_class_type not in (
            AccountClassType.STANDARD_ACCOUNT,
            AccountClassType.GOVCLOUD_ACCOUNT,
            AccountClassType.CHINA_ACCOUNT,
            AccountClassType.GERMANY_ACCOUNT,
        ):
            raise Exception(
                "The account_class_type={} is invalid.".format(self._account_class_type)
            )

    @classmethod
    def _process_sas_token(cls, sas_token):
        if sas_token and sas_token.startswith("?"):
            return sas_token[1:]
        return sas_token


def return_endpoint_suffix(account_class_type):
    endpoint_suffix = "core.windows.net"
    if account_class_type in (
        AccountClassType.STANDARD_ACCOUNT,
        AccountClassType.GOVCLOUD_ACCOUNT,
        AccountClassType.CHINA_ACCOUNT,
        AccountClassType.GERMANY_ACCOUNT,
    ):

        if account_class_type == AccountClassType.GOVCLOUD_ACCOUNT:
            endpoint_suffix = "core.usgovcloudapi.net"
        elif account_class_type == AccountClassType.CHINA_ACCOUNT:
            endpoint_suffix = "core.chinacloudapi.net"
        elif account_class_type == AccountClassType.GERMANY_ACCOUNT:
            endpoint_suffix = "core.cloudapi.de"
    else:
        raise Exception(
            "The account_class_type={} is unsupported by table service".format(
                account_class_type
            )
        )
    return endpoint_suffix


class TableStorageService(StorageService):
    def _create_service(self, logger):
        proxies = _get_proxy_dict(self._proxy_config, logger)
        sv = _create_table_service(
            account_name=self._account_name,
            account_secret_type=self._account_secret_type,
            account_secret=self._account_secret,
            account_class_type=self._account_class_type,
            proxies=proxies,
        )
        return sv

    def get_table_client(self, logger, table_name):
        table_service = self.get_service(logger)
        table_client = table_service.get_table_client(table_name)
        return table_client


class BlobStorageService(StorageService):
    def __init__(self, all_conf_contents, meta_config, task_config):
        super().__init__(all_conf_contents, meta_config, task_config)
        self._container_name = self._task_config[mscs_consts.CONTAINER_NAME]
        self._container_client = None

    def _create_service(self, logger):
        proxies = _get_proxy_dict(self._proxy_config, logger)
        sv = _create_blob_service(
            account_name=self._account_name,
            account_secret_type=self._account_secret_type,
            account_secret=self._account_secret,
            account_class_type=self._account_class_type,
            proxies=proxies,
        )
        return sv

    def get_container_client(self, logger):
        if not self._container_client:
            blob_service = self.get_service(logger)
            self._container_client = blob_service.get_container_client(
                self._container_name
            )
        return self._container_client

    def get_blob_client(self, logger, blob_name):
        container_client = self.get_container_client(logger)
        blob_client = container_client.get_blob_client(blob_name)
        return blob_client

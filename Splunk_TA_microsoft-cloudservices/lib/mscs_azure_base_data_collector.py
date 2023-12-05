#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from builtins import object
import abc

from azure.identity import ClientSecretCredential
from azure.common.credentials import ServicePrincipalCredentials
from azure.mgmt.resource.resources import ResourceManagementClient
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError, OAuth2Error
from requests import RequestException
from msrest import ServiceClient
from msrest.configuration import Configuration
from msrest.exceptions import (
    AuthenticationError,
    raise_with_traceback,
    TokenExpiredError,
    ClientRequestError,
)
from msrestazure import azure_cloud

import mscs_api_error as mae
import mscs_consts
import mscs_logger as logger
from mscs_util import proxy_from_config
from future.utils import with_metaclass


def _get_proxies(proxy_config):
    proxy_as_tuple = proxy_from_config(proxy_config)
    if not proxy_as_tuple:
        return None
    host, port, user, password = proxy_as_tuple
    if user and password:
        proxy_string = "{user}:{password}@{host}:{port}".format(
            user=user, password=password, host=host, port=port
        )
    else:
        proxy_string = "{host}:{port}".format(host=host, port=port)
    return {
        "http": "http://{}".format(proxy_string),
        "https": "http://{}".format(proxy_string),
    }


def _create_resource_client(credentials, subscription_id, base_url, proxies=None):
    """Create a ResourceManagementClient"""
    client = ResourceManagementClient(
        credential=credentials,
        subscription_id=str(subscription_id),
        base_url=base_url,
        proxies=proxies,
    )
    return client


class AzureBaseDataCollector(with_metaclass(abc.ABCMeta, object)):
    _NEXT_LINK = "nextLink"

    def __init__(self, all_conf_contents, task_config):
        self._all_conf_contents = all_conf_contents
        self._task_config = task_config
        self._subscription_id = task_config[mscs_consts.SUBSCRIPTION_ID]

        self._url = None
        self._api_version = None
        self._logger_prefix = None
        self._sourcetype = None

        self._global_settings = all_conf_contents.get(mscs_consts.GLOBAL_SETTINGS, {})
        self._proxies = _get_proxies(self._global_settings.get(mscs_consts.PROXY))

        self._parse_account_info()

        self._logger = logger.logger_for(self._get_logger_prefix())
        self._cloud_environment = self.get_cloud_env()
        self._manager_url = self._cloud_environment.endpoints.resource_manager
        self.authority_url = self._cloud_environment.endpoints.active_directory.lstrip(
            "https://"
        )

        # Setup mgmt resource client
        self._credentials = ClientSecretCredential(
            client_id=self._client_id,
            client_secret=self._client_secret,
            proxies=self._proxies,
            tenant_id=self._tenant_id,
            authority=self.authority_url,
        )
        self._resource_client = _create_resource_client(
            credentials=self._credentials,
            subscription_id=self._subscription_id,
            proxies=self._proxies,
            base_url=self._manager_url,
        )

        # Setup generic service client
        self._service_credentials = ServicePrincipalCredentials(
            client_id=self._client_id,
            secret=self._client_secret,
            proxies=self._proxies,
            tenant=self._tenant_id,
            cloud_environment=self._cloud_environment,
        )
        config = Configuration(base_url=self._manager_url)
        if self._proxies:
            for protocol, url in self._proxies.items():
                config.proxies.add(protocol, url)
        self._service = ServiceClient(creds=self._service_credentials, config=config)

    @abc.abstractmethod
    def collect_data(self):
        pass

    @abc.abstractmethod
    def _get_logger_prefix(self):
        pass

    def get_cloud_env(self):
        if self._account_class_type == "2":
            cloud_environment = azure_cloud.AZURE_US_GOV_CLOUD
            self._logger.info("gov_cloud selected as cloud environment")
        elif self._account_class_type == "3":
            cloud_environment = azure_cloud.AZURE_CHINA_CLOUD
        elif self._account_class_type == "4":
            cloud_environment = azure_cloud.AZURE_GERMAN_CLOUD
        else:
            cloud_environment = azure_cloud.AZURE_PUBLIC_CLOUD
            self._logger.info("pub_cloud selected as cloud environment")

        return cloud_environment

    def _parse_account_info(self):
        account_stanza_name = self._task_config[mscs_consts.ACCOUNT]
        account_info = self._all_conf_contents[mscs_consts.ACCOUNTS][
            account_stanza_name
        ]
        self._client_id = account_info[mscs_consts.CLIENT_ID]
        self._client_secret = account_info[mscs_consts.CLIENT_SECRET]
        self._tenant_id = account_info[mscs_consts.TENANT_ID]
        # Except for when upgrading from older version of add-on to gov supported
        try:
            self._account_class_type = account_info[mscs_consts.ACCOUNT_CLASS_TYPE]
        except KeyError:
            self._account_class_type = "1"

    def _parse_api_setting(self, api_stanza_name):
        api_setting = self._all_conf_contents[mscs_consts.API_SETTINGS][api_stanza_name]
        self._url = api_setting[mscs_consts.URL]
        self._api_version = api_setting[mscs_consts.API_VERSION]
        self._sourcetype = api_setting[mscs_consts.SOURCETYPE]
        return api_setting

    def _perform_request(self, url, **headers):
        r = self._service.get(url)
        try:
            response = self._service.send(
                request=r, headers=headers, proxies=self._proxies
            )
            result = response.json()
            self._error_check(response, result)
            return result
        except TokenExpiredError:
            self._logger.exception("Token is expired or invalid")
            raise
        except ClientRequestError:
            self._logger.exception("Error occurred in request url=%s", url)
            raise

    @staticmethod
    def _error_check(response, result):
        if response.status_code != 200 or (result and result.get("error")):
            err = result.get("error", {})
            code = err.get("code", result)
            message = err.get("message", result)
            raise mae.APIError(response.status_code, code, message)

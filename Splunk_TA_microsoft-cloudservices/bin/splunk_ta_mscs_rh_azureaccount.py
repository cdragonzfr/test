#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import logging
import traceback
import import_declare_test
from msrestazure.azure_active_directory import ServicePrincipalCredentials
from msrestazure import azure_cloud

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

from mscs_util import (
    mscs_consts,
    get_proxy_info_from_endpoint,
    get_logger,
    check_account_isvalid,
)

util.remove_http_proxy_env_vars()


# Copy the defination from mscs_storage_services.py
# Avoid the indirect dependency on azure.storage
# Because the host process of rest handlers might load wrong libraries belongs to other apps.
class AccountClassType(object):
    STANDARD_ACCOUNT = 1
    GOVCLOUD_ACCOUNT = 2
    CHINA_ACCOUNT = 3
    GERMANY_ACCOUNT = 4


class AzureAccountValidation(validator.Validator):
    def __init__(self):

        super(AzureAccountValidation, self).__init__()
        self.put_msg(
            "Account authentication failed. Please check your credentials and try again"
        )
        self.client_id = None
        self.client_secret = None
        self.tenant_id = None
        self.cloud_environment = None
        self.proxy_config = None

    def validate(self, value, data):
        """Validate the given values.

        :param value: Value of particular parameter
        :param data: Whole payload
        :return: True if validation pass, False otherwise.
        """

        logger = get_logger(
            "splunk_ta_microsoft-cloudservices_azure_account_validation"
        )

        logger.info("Verifying credentials for MSCS Azure account")

        self.client_id = data.get(mscs_consts.CLIENT_ID)
        if not self.client_id:
            return False

        self.client_secret = data.get(mscs_consts.CLIENT_SECRET)
        if not self.client_secret:
            return False

        self.tenant_id = data.get(mscs_consts.TENANT_ID)
        if not self.tenant_id:
            return False

        account_class_type = data.get(mscs_consts.ACCOUNT_CLASS_TYPE)
        if not account_class_type:
            return False

        # Set cloud environment based on the class type.
        # Currently only US gov cloud and public cloud are supported
        if account_class_type == str(AccountClassType.GOVCLOUD_ACCOUNT):
            self.cloud_environment = azure_cloud.AZURE_US_GOV_CLOUD
        else:
            self.cloud_environment = azure_cloud.AZURE_PUBLIC_CLOUD

        logger.info("Getting proxy details")
        # Get proxy details and return False if any issue occurs while getting the details
        try:
            self.proxy_config = get_proxy_info_from_endpoint()
        except Exception as e:
            logger.error(
                "Error {} while getting proxy details: {}".format(
                    e, traceback.format_exc()
                )
            )
            return False

        proxy_dict = {}

        # If proxy details are available and proxy is enabled
        if (
            self.proxy_config.get(mscs_consts.PROXY_ENABLED)
            and self.proxy_config[mscs_consts.PROXY_ENABLED] != "0"
        ):

            logger.info("Proxy is enabled")

            # Both proxy_url and proxy_port are provided
            if not all(
                (
                    self.proxy_config.get(mscs_consts.PROXY_URL),
                    self.proxy_config.get(mscs_consts.PROXY_PORT),
                )
            ):
                logger.info("Proxy host or port is invalid")
                return False

            # Prepare the proxy string according to the format
            proxy_string = "{host}:{port}".format(
                host=self.proxy_config[mscs_consts.PROXY_URL],
                port=self.proxy_config[mscs_consts.PROXY_PORT],
            )

            # If both proxy_username and proxy_password are provided, include them in the proxy_string
            if self.proxy_config.get(
                mscs_consts.PROXY_USERNAME
            ) and self.proxy_config.get(mscs_consts.PROXY_PASSWORD):
                proxy_string = "{user}:{password}@{proxy_string}".format(
                    user=self.proxy_config[mscs_consts.PROXY_USERNAME],
                    password=self.proxy_config[mscs_consts.PROXY_PASSWORD],
                    proxy_string=proxy_string,
                )
            logger.info(
                "Changing proxy schemes to http as only http proxy is supported"
            )
            proxy_dict = {
                "http": "http://{}".format(proxy_string),
                "https": "http://{}".format(proxy_string),
            }

        try:
            service = ServicePrincipalCredentials(
                client_id=self.client_id,
                secret=self.client_secret,
                tenant=self.tenant_id,
                cloud_environment=self.cloud_environment,
                proxies=proxy_dict,
            )
        except Exception as e:
            logger.error(
                "Error {} while verifying the credentials: {}".format(
                    e, traceback.format_exc()
                )
            )
            return False

        logger.info("Credentials validated successfully")
        return True


class AzureAccountHandler(AdminExternalHandler):
    """
    This handler is to check if the account configurations are valid or not
    """

    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        check_account_isvalid(confInfo, self.getSessionKey(), account_type="azure")

    def handleEdit(self, confInfo):
        AdminExternalHandler.handleEdit(self, confInfo)
        edited_account = next(iter(confInfo))
        confInfo[edited_account]["isvalid"] = "true"

    def handleCreate(self, confInfo):
        AdminExternalHandler.handleCreate(self, confInfo)
        edited_account = next(iter(confInfo))
        confInfo[edited_account]["isvalid"] = "true"


fields = [
    field.RestField(
        "client_id", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "client_secret", required=True, encrypted=True, default=None, validator=None
    ),
    field.RestField(
        "tenant_id",
        required=True,
        encrypted=False,
        default=None,
        validator=AzureAccountValidation(),
    ),
    field.RestField(
        "account_class_type",
        required=True,
        encrypted=False,
        default="1",
        validator=None,
    ),
    field.RestField(
        "app_account_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


endpoint = SingleModel("mscs_azure_accounts", model, config_name="azureaccount")


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AzureAccountHandler,
    )

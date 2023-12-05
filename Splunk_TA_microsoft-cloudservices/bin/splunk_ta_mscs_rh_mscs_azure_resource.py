#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import import_declare_test
from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging
import mscs_util

util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        "account", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "subscription_id", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "resource_type",
        required=True,
        encrypted=False,
        default="virtual_machine",
        validator=None,
    ),
    field.RestField(
        "resource_group_list",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "interval",
        required=True,
        encrypted=False,
        default="3600",
        validator=validator.Number(
            max_val=31536000,
            min_val=1,
        ),
    ),
    field.RestField(
        "index",
        required=True,
        encrypted=False,
        default="default",
        validator=validator.String(
            max_len=80,
            min_len=1,
        ),
    ),
    field.RestField(
        "resource_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]


class AzureResourceInputHandler(AdminExternalHandler):
    """
    Custom handler to set the default start_time value as 30 days ago and
    check if the account configuration is valid or not.
    """

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="azure"
        )

    def handleEdit(self, confInfo):
        AdminExternalHandler.handleEdit(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="azure"
        )

    def handleCreate(self, confInfo):
        AdminExternalHandler.handleCreate(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="azure"
        )


model = RestModel(fields, name=None)


endpoint = SingleModel(
    "mscs_azure_resource_inputs", model, config_name="mscs_azure_resource"
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AzureResourceInputHandler,
    )

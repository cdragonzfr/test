#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# isort: skip_file # noqa: E265

# fmt: on
import import_declare_test  # noqa: F401
from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging
import mscs_util

# fmt: on

util.remove_http_proxy_env_vars()

fields = [
    field.RestField(
        "account", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "event_hub_namespace",
        required=True,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "event_hub_name", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "consumer_group", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "max_wait_time", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "max_batch_size", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "use_amqp_over_websocket",
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
        "sourcetype",
        required=True,
        encrypted=False,
        default="mscs:azure:eventhub:event",
        validator=None,
    ),
    field.RestField(
        "blob_checkpoint_enabled",
        required=False,
        encrypted=False,
        default=False,
        validator=None,
    ),
    field.RestField(
        "storage_account",
        required=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "container_name", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField("disabled", required=False, validator=None),
]


class AzureEventHubInputHandler(AdminExternalHandler):
    """
    Custom handler to check if the account configuration is valid or not
    """

    def handleCreate(self, confInfo):
        status = True

        if (
            not "disabled" in self.callerArgs
            and not "enabled" in self.callerArgs
            and "blob_checkpoint_enabled" in self.callerArgs
        ):
            if (
                self.callerArgs["blob_checkpoint_enabled"] == "1"
                or self.callerArgs["blob_checkpoint_enabled"][0] == "1"
            ):
                status = mscs_util.check_account_secret_isvalid(
                    confInfo,
                    self.getSessionKey(),
                    account_type="storage",
                    storage_account=self.callerArgs["storage_account"],
                )
        if status:
            AdminExternalHandler.handleCreate(self, confInfo)
            mscs_util.check_account_isvalid(
                confInfo, self.getSessionKey(), account_type="azure"
            )
        else:
            raise ValueError("The account_secret_type NONE_SECRET is not supported.")

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="azure"
        )

    def handleEdit(self, confInfo):
        status = True
        if (
            not "disabled" in self.callerArgs
            and not "enabled" in self.callerArgs
            and "blob_checkpoint_enabled" in self.callerArgs
        ):
            if (
                self.callerArgs["blob_checkpoint_enabled"] == "1"
                or self.callerArgs["blob_checkpoint_enabled"][0] == "1"
            ):
                status = mscs_util.check_account_secret_isvalid(
                    confInfo,
                    self.getSessionKey(),
                    account_type="storage",
                    storage_account=self.callerArgs["storage_account"],
                )
        if status:
            AdminExternalHandler.handleEdit(self, confInfo)
            mscs_util.check_account_isvalid(
                confInfo, self.getSessionKey(), account_type="azure"
            )
        else:
            raise ValueError("The account_secret_type NONE_SECRET is not supported.")


model = RestModel(fields, name=None)


endpoint = DataInputModel(
    "mscs_azure_event_hub",
    model,
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AzureEventHubInputHandler,
    )

#!/usr/bin/python
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
    DataInputModel,
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
        "container_name", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "prefix",
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=4000,
            min_len=0,
        ),
    ),
    field.RestField(
        "blob_list", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "blob_mode", required=False, encrypted=False, default="random", validator=None
    ),
    field.RestField(
        "is_migrated", required=False, encrypted=False, default="0", validator=None
    ),
    field.RestField(
        "exclude_blob_list",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "log_type", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "guids", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "application_insights",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "decoding", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "collection_interval",
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
        default="mscs:storage:blob",
        validator=None,
    ),
    field.RestField(
        "blob_input_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]


class StorageBlobInputHandler(AdminExternalHandler):
    """
    Custom handler to check if the account configuration is valid or not
    """

    def handleCreate(self, confInfo):
        self.payload["is_migrated"] = "1"
        AdminExternalHandler.handleCreate(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )

    def handleEdit(self, confInfo):
        AdminExternalHandler.handleEdit(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )


model = RestModel(fields, name=None)


endpoint = DataInputModel(
    "mscs_storage_blob",
    model,
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=StorageBlobInputHandler,
    )

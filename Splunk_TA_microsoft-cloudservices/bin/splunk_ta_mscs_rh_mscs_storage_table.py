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
        "storage_table_type",
        required=True,
        encrypted=False,
        default="storage_table",
        validator=None,
    ),
    field.RestField(
        "table_list", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "start_time", required=False, encrypted=False, default=None, validator=None
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
        default="mscs:storage:table",
        validator=None,
    ),
    field.RestField(
        "storage_input_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "storage_virtual_metrics_input_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


class StorageTableInputHandler(AdminExternalHandler):
    """
    Custom handler to set the default start_time value as 30 days ago and
    check if the account configuration is valid or not.
    """

    def update_start_time(self):
        if not self.payload.get("start_time"):
            self.payload["start_time"] = mscs_util.get_30_days_ago_local_time(
                self.getSessionKey()
            )

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )

    def handleCreate(self, confInfo):
        self.update_start_time()
        AdminExternalHandler.handleCreate(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )

    def handleEdit(self, confInfo):
        self.update_start_time()
        AdminExternalHandler.handleEdit(self, confInfo)
        mscs_util.check_account_isvalid(
            confInfo, self.getSessionKey(), account_type="storage"
        )


endpoint = DataInputModel(
    "mscs_storage_table",
    model,
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=StorageTableInputHandler,
    )

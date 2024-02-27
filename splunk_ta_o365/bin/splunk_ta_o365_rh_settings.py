#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import splunk_ta_o365_bootstrap
import logging

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    MultipleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

util.remove_http_proxy_env_vars()

fields_logging = [
    field.RestField(
        "log_level", required=True, encrypted=False, default="INFO", validator=None
    )
]
model_logging = RestModel(fields_logging, name="logging")


fields_proxy = [
    field.RestField(
        "proxy_enabled", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "host",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=4096,
                min_len=0,
            ),
            validator.Pattern(
                regex=r"""^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9])$""",
            ),
        ),
    ),
    field.RestField(
        "port",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.Number(
                max_val=65535,
                min_val=1,
            ),
            validator.Pattern(
                regex=r"""^[0-9]+$""",
            ),
        ),
    ),
    field.RestField(
        "username",
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=50,
            min_len=1,
        ),
    ),
    field.RestField(
        "password", required=False, encrypted=True, default=None, validator=None
    ),
]
model_proxy = RestModel(fields_proxy, name="proxy")


endpoint = MultipleModel(
    "splunk_ta_o365_settings",
    models=[model_logging, model_proxy],
)


class SettingsRestHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleCreate(self, confInfo):
        if "proxy_enabled" in self.payload:
            self.payload["is_conf_migrated"] = 1
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleEdit(self, confInfo):
        if "proxy_enabled" in self.payload:
            self.payload["is_conf_migrated"] = 1
        AdminExternalHandler.handleEdit(self, confInfo)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=SettingsRestHandler,
    )

#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import import_declare_test
from splunktaucclib.rest_handler.endpoint import (
    field,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging

util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        "url", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "api_version", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "sourcetype", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "instance_view_url",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
]
model = RestModel(fields, name=None)

endpoint = SingleModel("mscs_api_settings", model, config_name="mscs_api_settings")


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )

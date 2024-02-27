#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import splunk_ta_o365_bootstrap

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging

from rh_common import graph_api_list_remove_item

util.remove_http_proxy_env_vars()

CONTENT_TYPES = ["AuditLogs.SignIns"]


fields = [
    field.RestField(
        "tenant_name", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "content_type", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "index", required=True, encrypted=False, default="default", validator=None
    ),
    field.RestField(
        "interval",
        required=True,
        encrypted=False,
        default="300",
        validator=validator.Pattern(
            regex=r"""^\-[1-9]\d*$|^\d*$""",
        ),
    ),
    field.RestField(
        "request_timeout",
        required=False,
        encrypted=False,
        default="60",
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^[1-9]\d*$""",
            ),
            validator.Number(
                max_val=600,
                min_val=10,
            ),
        ),
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


endpoint = DataInputModel(
    "splunk_ta_o365_graph_api",
    model,
)


class AuditLogsInputRestHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)

        graph_api_list_remove_item(confInfo, CONTENT_TYPES)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AuditLogsInputRestHandler,
    )

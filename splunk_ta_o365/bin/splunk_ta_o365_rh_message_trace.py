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
from datetime import datetime, timedelta
from rh_common import UTCDateValidator

util.remove_http_proxy_env_vars()


class MessageTraceValidator(validator.Validator):
    def __init__(self):
        super(MessageTraceValidator, self).__init__()

    def validate(self, value, data):
        return self.date_validations(data)

    def date_validations(self, data):
        now = datetime.utcnow()
        start_date_time = datetime.strptime(
            data.get("start_date_time"), "%Y-%m-%dT%H:%M:%S"
        )
        if start_date_time > now:
            self.put_msg("The Start date/time cannot be in the future")
            return False
        old_date = now - timedelta(days=10)
        if start_date_time < old_date:
            self.put_msg("Start date/time cannot be older than 10 days in the past.")
            return False
        if data.get("input_mode") == "index_once":
            end_date_time = datetime.strptime(
                data.get("end_date_time"), "%Y-%m-%dT%H:%M:%S"
            )
            if end_date_time > now:
                self.put_msg("The End date/time cannot be in the future")
                return False
            if start_date_time > end_date_time:
                self.put_msg(
                    "The Start date/time cannot be ahead of the End date/time."
                )
                return False
        return True


fields = [
    field.RestField(
        "message_trace_input_configuration_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "input_mode",
        required=True,
        encrypted=False,
        default="continuously_monitor",
        validator=None,
    ),
    field.RestField(
        "start_date_time",
        required=False,
        encrypted=False,
        default=None,
        validator=UTCDateValidator(),
    ),
    field.RestField(
        "end_date_time",
        required=False,
        encrypted=False,
        default=None,
        validator=UTCDateValidator(),
    ),
    field.RestField(
        "tenant_name",
        required=True,
        encrypted=False,
        default=None,
        validator=MessageTraceValidator(),
    ),
    field.RestField(
        "index",
        required=True,
        encrypted=False,
        default="default",
        validator=validator.Pattern(
            regex=r"""^^[A-Za-z0-9][\w-]*$""",
        ),
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
        "query_window_size",
        required=False,
        encrypted=False,
        default="60",
        validator=None,
    ),
    field.RestField(
        "delay_throttle",
        required=False,
        encrypted=False,
        default="1440",
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)

endpoint = DataInputModel(
    "splunk_ta_o365_message_trace",
    model,
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )

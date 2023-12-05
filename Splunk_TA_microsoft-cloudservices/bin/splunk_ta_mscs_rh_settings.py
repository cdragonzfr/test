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
    MultipleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunktaucclib.rest_handler.endpoint.validator import Validator

import logging

util.remove_http_proxy_env_vars()


class ProxyValidation(Validator):
    """
    Validate Proxy details provided
    """

    def __init__(self, *args, **kwargs):
        super(ProxyValidation, self).__init__(*args, **kwargs)

    def validate(self, value, data):
        username_val = data.get("proxy_username")
        password_val = data.get("proxy_password")

        # If password is specified, then username is required
        if password_val and not username_val:
            self.put_msg(
                "Username is required if password is specified", high_priority=True
            )
            return False
        # If username is specified, then password is required
        elif username_val and not password_val:
            self.put_msg(
                "Password is required if username is specified", high_priority=True
            )
            return False

        # If length of username is not satisfying the String length criteria
        if username_val:
            str_len = len(username_val)
            _min_len = 1
            _max_len = 50
            if str_len < _min_len or str_len > _max_len:
                msg = (
                    "String length of username should be between %(min_len)s and %(max_len)s"
                    % {"min_len": _min_len, "max_len": _max_len}
                )
                self.put_msg(msg, high_priority=True)
                return False

        return True


fields_proxy = [
    field.RestField(
        "proxy_enabled", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "proxy_type", required=True, encrypted=False, default="http", validator=None
    ),
    field.RestField(
        "proxy_rdns", required=False, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "proxy_url",
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
        "proxy_port",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        ),
    ),
    field.RestField(
        "proxy_username",
        required=False,
        encrypted=False,
        default=None,
        validator=ProxyValidation(),
    ),
    field.RestField(
        "proxy_password",
        required=False,
        encrypted=True,
        default=None,
        validator=ProxyValidation(),
    ),
]
model_proxy = RestModel(fields_proxy, name="proxy")


fields_logging = [
    field.RestField(
        "agent", required=False, encrypted=False, default="INFO", validator=None
    )
]
model_logging = RestModel(fields_logging, name="logging")

fields_advanced = [
    field.RestField(
        "delete_storageblob_ckpt_files",
        required=False,
        encrypted=False,
        default="0",
        validator=None,
    )
]
model_advanced = RestModel(fields_advanced, name="advanced")


fields_performance_tuning_settings = [
    field.RestField(
        "worker_threads_num",
        required=False,
        encrypted=False,
        default="10",
        validator=None,
    ),
    field.RestField(
        "query_entities_page_size",
        required=False,
        encrypted=False,
        default="1000",
        validator=None,
    ),
    field.RestField(
        "event_cnt_per_item",
        required=False,
        encrypted=False,
        default="100",
        validator=None,
    ),
    field.RestField(
        "query_end_time_offset",
        required=False,
        encrypted=False,
        default="180",
        validator=None,
    ),
    field.RestField(
        "get_blob_batch_size",
        required=False,
        encrypted=False,
        default="120000",
        validator=None,
    ),
    field.RestField(
        "http_timeout", required=False, encrypted=False, default="120", validator=None
    ),
]

model_performance_tuning_settings = RestModel(
    fields_performance_tuning_settings, name="performance_tuning_settings"
)


endpoint = MultipleModel(
    "splunk_ta_mscs_settings",
    models=[
        model_proxy,
        model_logging,
        model_advanced,
        model_performance_tuning_settings,
    ],
)


class CustomMSCSSettingsHandler(AdminExternalHandler):
    """
    Custom Handler to support handleList for MultiModel if no callerArgs is provided
    """

    CONF_MODEL_LIST = ["logging", "proxy", "advanced", "performance_tuning_settings"]

    def handleList(self, confInfo):
        if self.callerArgs.id:
            setting_models = [self.callerArgs.id]
        else:
            setting_models = self.CONF_MODEL_LIST

        for each_model in setting_models:
            self.callerArgs.id = each_model
            AdminExternalHandler.handleList(self, confInfo)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=CustomMSCSSettingsHandler,
    )

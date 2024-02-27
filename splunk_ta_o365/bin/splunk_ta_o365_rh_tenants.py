#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import splunk_ta_o365_bootstrap
import sys
import json
import urllib.parse
import logging

import requests
from requests.packages import urllib3  # type: ignore
from solnlib import utils as sutils

from solnlib import conf_manager
from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler.error import RestError
from splunktaucclib.rest_handler import admin_external, util, error
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

util.remove_http_proxy_env_vars()

APP_NAME = "splunk_ta_o365"

from splunk_ta_o365.common.utils import get_logger

logger = get_logger("splunk_ta_o365_rest_handlers")

fields = [
    field.RestField(
        "endpoint", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "tenant_id",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Pattern(
            regex=r"""^[0-9a-fA-F]{8}(\-[0-9a-fA-F]{4}){3}\-[0-9a-fA-F]{12}$""",
        ),
    ),
    field.RestField(
        "client_id",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Pattern(
            regex=r"""^[0-9a-fA-F]{8}(\-[0-9a-fA-F]{4}){3}\-[0-9a-fA-F]{12}$""",
        ),
    ),
    field.RestField(
        "change_client_secret",
        required=False,
        encrypted=False,
        default=0,
        validator=None,
    ),
    field.RestField(
        "client_secret", required=False, encrypted=True, default=None, validator=None
    ),
    field.RestField(
        "change_cas_secret", required=False, encrypted=False, default=0, validator=None
    ),
    field.RestField(
        "cloudappsecuritytoken",
        required=False,
        encrypted=True,
        default=None,
        validator=None,
    ),
    field.RestField(
        "cas_portal_url",
        required=False,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=63,
                min_len=1,
            ),
            validator.Pattern(
                regex=r"""^([A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)$""",
            ),
        ),
    ),
    field.RestField(
        "cas_portal_data_center",
        required=False,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=63,
                min_len=1,
            ),
            validator.Pattern(
                regex=r"""^([A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)$""",
            ),
        ),
    ),
]
model = RestModel(fields, name=None)

endpoint = SingleModel("splunk_ta_o365_tenants", model, config_name="tenants")


class TenantValidator:
    def __init__(
        self, session_key, tenant_name=None, updated_tenant=None, is_create=False
    ):
        self._session_key = session_key
        self._tenant_name = tenant_name
        self._updated_tenant = updated_tenant
        self._is_create = is_create
        self._session = requests

    def _response(self, status, data=None):
        if not data:
            data = {"status": status, "entry": []}
        payload = json.dumps(data)
        return {"status": status, "payload": payload}

    def _error(self, status, text=None, trace=None):
        payload = json.dumps(
            {"messages": [{"text": text, "type": "ERROR"}], "trace": trace}
        )
        return {"status": status, "payload": payload}

    def _convert(self, value):
        return value.encode("utf-8") if sys.version_info < (3,) else value

    def _get_conf_content(self, conf_name, stanza_name=None, is_creds_include=False):
        cfm = None
        if is_creds_include:
            cfm = conf_manager.ConfManager(
                self._session_key,
                APP_NAME,
                realm=f"__REST_CREDENTIAL__#{APP_NAME}#configs/conf-{conf_name}",
            )
        else:
            cfm = conf_manager.ConfManager(self._session_key, APP_NAME)

        conf = cfm.get_conf(conf_name)
        conf_content = conf.get(stanza_name=stanza_name, only_current_app=True)
        return conf_content

    def _load_existing_tenant(self, name):
        conf_name = "splunk_ta_o365_tenants"
        ext_tenant = self._get_conf_content(conf_name, name, is_creds_include=True)

        tenant = {
            "endpoint": ext_tenant.get("endpoint"),
            "tenant_id": ext_tenant.get("tenant_id"),
            "client_id": ext_tenant.get("client_id"),
            "client_secret": ext_tenant.get("client_secret"),
            "cas_portal_data_center": ext_tenant.get("cas_portal_data_center"),
            "cas_portal_url": ext_tenant.get("cas_portal_url"),
            "cloudappsecuritytoken": ext_tenant.get("cloudappsecuritytoken"),
        }

        return tenant

    def _load_proxy(self):
        conf_name = "splunk_ta_o365_settings"
        conf_content = self._get_conf_content(conf_name, "proxy", is_creds_include=True)

        enabled = conf_content.get("proxy_enabled")

        if sutils.is_false(enabled):
            return None

        proxy_type = "http"
        host = conf_content.get("host", "")
        port = conf_content.get("port", "")
        username = conf_content.get("username", "")
        password = conf_content.get("password", "")

        endpoint = f"{host}:{port}"
        auth = None
        if username and len(username) > 0:
            auth = urllib.parse.quote(username.encode(), safe="")
            if password and len(password) > 0:
                auth += ":"
                auth += urllib.parse.quote(password.encode(), safe="")

        if auth:
            endpoint = auth + "@" + endpoint

        url = f"{proxy_type}://{endpoint}"
        return {"http": url, "https": url}

    def _load_endpoint(self, endpoint):
        conf_name = "splunk_ta_o365_endpoints"
        conf_content = self._get_conf_content(conf_name, endpoint)

        return (
            conf_content.get("Login"),
            conf_content.get("Management"),
            conf_content.get("Graph"),
            conf_content.get("CloudAppSecurity"),
            conf_content.get("MessageTrace"),
        )

    def _validate_credentials_v2(
        self, proxy, login, resource, tenant_id, client_id, client_secret
    ):
        login = self._convert(login)
        tenant_id = self._convert(tenant_id)

        scope = resource + "/.default"

        url = urllib.parse.urljoin(login, f"/{tenant_id}/oauth2/v2.0/token")
        response = self._session.request(
            "POST",
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
            proxies=proxy,
        )

        if response.status_code != 200:
            default_msg = (
                f"Unknown server response with status code {response.status_code}."
                " Please re-check provided client credentials."
            )
            trace = response.json()
            msg = trace.get("error_description", default_msg)
            return False, self._error(400, msg, trace)
        return True, self._response(200)

    def _validate_cas_token(
        self,
        proxy,
        cloudappsecurity,
        cloudappsecuritytoken,
        casPortalUrl,
        casPortalDataCenter,
    ):
        cloudappsecuritytoken = self._convert(cloudappsecuritytoken)
        cas_subdomain = (
            self._convert(casPortalUrl) + "." + self._convert(casPortalDataCenter)
        )
        cloudappsecurity = self._convert(cloudappsecurity)
        cloudappsecurity = cloudappsecurity.replace(
            "tenant_subdomain.tenant_data_center", cas_subdomain
        )

        url = urllib.parse.urljoin(cloudappsecurity, "/api/v1/{}/".format("alerts"))

        try:
            response = self._session.request(
                "GET",
                url,
                headers={
                    "Authorization": f"Token {cloudappsecuritytoken}",
                    "Content-Type": "application/json",
                },
                proxies=proxy,
            )
        except Exception as exc:  # noqa: F841
            return False, self._error(400, "Invalid Tenant Data Center.")

        if response.status_code != 200:
            trace = response.json()
            default_msg = (
                f"Unknown server response with status code {response.status_code}."
                " Please re-check provided Cloud App Security credentials."
            )
            msg = trace.get("error_description", trace.get("detail", default_msg))
            if msg != default_msg:
                msg = f"Please re-check provided Cloud App Security credentials. Error: {msg}"
            return False, self._error(400, msg, trace)
        return True, self._response(200)

    def validate(self):
        try:
            tenant = (
                self._load_existing_tenant(self._tenant_name)
                if not self._is_create
                else dict()
            )

            tenant_id = self._updated_tenant.get("tenant_id")
            client_id = self._updated_tenant.get("client_id")
            client_secret = (
                tenant.get("client_secret")
                if not self._is_create
                and self._updated_tenant["change_client_secret"] == "0"
                else self._updated_tenant.get("client_secret")
            )
            cloudappsecuritytoken = (
                tenant.get("cloudappsecuritytoken")
                if not self._is_create
                and self._updated_tenant["change_cas_secret"] == "0"
                else self._updated_tenant.get("cloudappsecuritytoken")
            )
            casPortalUrl = self._updated_tenant.get("cas_portal_url")
            casPortalDataCenter = self._updated_tenant.get("cas_portal_data_center")
            endpoint = self._updated_tenant.get("endpoint")

            login, mgmt, graph, cloudappsecurity, messagetrace = self._load_endpoint(
                endpoint
            )
            proxy = self._load_proxy()

            if tenant_id:
                if login and (mgmt or graph or messagetrace):
                    is_valid_mgmt = is_valid_graph = is_valid_messagetrace = False

                    if mgmt:
                        logger.info(f"Validating Management API, {mgmt}")
                        is_valid_mgmt, mgmt_res = self._validate_credentials_v2(
                            proxy, login, mgmt, tenant_id, client_id, client_secret
                        )
                        if not is_valid_mgmt:
                            logger.error(
                                f"Validation failed for the Management API. Reason: {mgmt_res}"
                            )
                    if graph:
                        logger.info(f"Validating Graph API, {graph}")
                        is_valid_graph, graph_res = self._validate_credentials_v2(
                            proxy, login, graph, tenant_id, client_id, client_secret
                        )
                        if not is_valid_graph:
                            logger.error(
                                f"Validation failed for the Graph API. Reason: {graph_res}"
                            )
                    if messagetrace:
                        (
                            is_valid_messagetrace,
                            messagetrace_res,
                        ) = self._validate_credentials_v2(
                            proxy,
                            login,
                            messagetrace,
                            tenant_id,
                            client_id,
                            client_secret,
                        )
                        if not is_valid_messagetrace:
                            logger.error(
                                f"Validation failed for the Message Trace API. Reason: {messagetrace_res}"
                            )

                    if not (is_valid_mgmt or is_valid_graph or is_valid_messagetrace):
                        if not is_valid_mgmt:
                            return mgmt_res
                        if not is_valid_graph:
                            return graph_res
                        if not is_valid_messagetrace:
                            return messagetrace_res
                else:
                    logger.error(
                        "Graph/Management/MessageTrace APIs for the selected 'Endpoint' not found."
                    )
                    return self._error(
                        400,
                        "Graph/Management/MessageTrace APIs for the selected 'Endpoint' not found.",
                    )

            if cloudappsecuritytoken:
                if cloudappsecurity:
                    is_valid, cloud_res = self._validate_cas_token(
                        proxy,
                        cloudappsecurity,
                        cloudappsecuritytoken,
                        casPortalUrl,
                        casPortalDataCenter,
                    )
                    if not is_valid:
                        logger.error(
                            f"Validation failed for the Cloud App Security APIs. Reason: {cloud_res}"
                        )
                        return cloud_res
                else:
                    logger.error(
                        "Cloud App Security APIs for the selected 'Endpoint' not found."
                    )
                    return self._error(
                        400,
                        "Cloud App Security APIs for the selected 'Endpoint' not found.",
                    )
            logger.info("Tenant validated successfully.")
            return self._response(200)
        except Exception as e:
            logger.error(
                f"Error occurred while validating the tenant. Error: {str(e)}",
                exc_info=True,
            )
            return self._error(500, str(e))


class TenantHandler(AdminExternalHandler):
    """
    Custom handler to handle Tenant operations
    """

    def _remove_change_secret_params(self):
        # remove change secret parameters which are required for UI behaviour
        # and not in data collection
        if "change_client_secret" in self.payload:
            del self.payload["change_client_secret"]
        if "change_cas_secret" in self.payload:
            del self.payload["change_cas_secret"]

    def _validate(self, name, updated_tenant, is_create=False):
        tenant_validator = TenantValidator(
            self.getSessionKey(), name, updated_tenant, is_create
        )
        result = tenant_validator.validate()
        if result.get("status") < 200 or result.get("status") >= 300:
            message = result.get("payload")
            try:
                payload_dict = json.loads(message)
                messages = payload_dict.get("messages")
                if messages:
                    message = messages[0].get("text")
            except Exception as e:
                msg = f"Error={e}, Error Detail={result}"
                logger.error(msg)
                return "Unexpected error", msg
            return result.get("status"), message
        return None, None

    def handleCreate(self, confInfo):
        name = self.callerArgs.id
        updated_tenant = self.payload.copy()
        status, message = self._validate(name, updated_tenant, is_create=True)
        if status:
            raise RestError(status, message)
        self._remove_change_secret_params()
        self.payload["is_conf_migrated"] = 1
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleEdit(self, confInfo):
        name = self.callerArgs.id
        updated_tenant = self.payload.copy()
        status, message = self._validate(name, updated_tenant, is_create=False)
        if status:
            raise RestError(status, message)
        if self.payload["change_client_secret"] == "0":
            del self.payload["client_secret"]
        if self.payload["change_cas_secret"] == "0":
            del self.payload["cloudappsecuritytoken"]
        self._remove_change_secret_params()
        self.payload["is_conf_migrated"] = 1
        AdminExternalHandler.handleEdit(self, confInfo)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=TenantHandler,
    )

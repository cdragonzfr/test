#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import time
from splunk_ta_o365.common.token import (
    O365CloudAppSecurityPSKPolicy,
    O365v2TokenPSKPolicy,
    O365MessageTracePSKPolicy,
)
from splunksdc.config import StanzaParser, StringField, BooleanField
from splunksdc import logging

logger = logging.get_module_logger()


class O365Tenant:
    @classmethod
    def create(cls, config, tenant_name):
        profile = None
        conf_name = "splunk_ta_o365_tenants"

        retry = 0
        while True:
            config.clear(conf_name, stanza=tenant_name, virtual=True)
            content = config.load(conf_name, tenant_name, virtual=True)
            parser = StanzaParser(
                [
                    StringField("endpoint"),
                    StringField("tenant_id"),
                    StringField("client_id"),
                    StringField("client_secret"),
                    StringField("cloudappsecuritytoken"),
                    StringField("cas_portal_url"),
                    StringField("cas_portal_data_center"),
                    BooleanField("is_conf_migrated"),
                ]
            )
            profile = parser.parse(content)

            if profile.is_conf_migrated:
                break
            if retry == 4:
                break
            retry += 1
            logger.info("Waiting for Tenant Conf migration to be completed")
            time.sleep(60)

        return O365Tenant(
            profile.endpoint,
            profile.tenant_id,
            profile.client_id,
            profile.client_secret,
            profile.cloudappsecuritytoken,
            profile.cas_portal_url,
            profile.cas_portal_data_center,
        )

    def __init__(
        self,
        endpoint,
        tenant_id,
        client_id,
        client_secret,
        cloudappsecuritytoken,
        cas_portal_url,
        cas_portal_data_center,
    ):
        self._realm = endpoint
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._cloudappsecuritytoken = cloudappsecuritytoken
        self._cas_portal_url = cas_portal_url
        self._cas_portal_data_center = cas_portal_data_center

    def create_management_portal(self, registry):
        return registry("Management", self._tenant_id, self._realm)

    def create_graph_portal(self, registry):
        return registry("Graph", self._tenant_id, self._realm)

    def create_cas_portal(self, registry):
        return registry("CloudAppSecurity", self._tenant_id, self._realm)

    def create_messagetrace_portal(self, registry):
        return registry("MessageTrace", self._tenant_id, self._realm)

    def create_v2_token_policy(self, registry):
        login = registry("Login", self._tenant_id, self._realm)
        return O365v2TokenPSKPolicy(login, self._client_id, self._client_secret)

    def create_cas_token_policy(self, registry):
        login = registry("Login", self._tenant_id, self._realm)
        return O365CloudAppSecurityPSKPolicy(
            login,
            self._tenant_id,
            self._cloudappsecuritytoken,
            self._cas_portal_url,
            self._cas_portal_data_center,
        )

    def create_messagetrace_token_policy(self, registry):
        login = registry("Login", self._tenant_id, self._realm)
        return O365MessageTracePSKPolicy(login, self._client_id, self._client_secret)

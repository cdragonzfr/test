#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

# This script is used to migrate proxy and passwords after upgrading
# to make proxy and passwords compliant to UCC standard

import sys
import time
from urllib.parse import urlparse

import requests
import splunk_ta_o365_bootstrap
from solnlib import utils as sutils
from solnlib.conf_manager import ConfManager
from solnlib.splunk_rest_client import SplunkRestClient
from solnlib.splunkenv import get_splunkd_uri
from splunk_ta_o365.common.utils import get_logger
from splunklib.client import Service

logger = get_logger("splunk_ta_o365_conf_migration")
APP_NAME = "splunk_ta_o365"
SETTINGS_CONF_FILE_NAME = "splunk_ta_o365_settings"
TENANTS_CONF_FILE_NAME = "splunk_ta_o365_tenants"


def get_session_key():
    """
    This function is used to get the session key.
    :return: This function returns the session_key value.
    """
    session_key = None
    try:
        session_key = sys.stdin.readline().strip()
    except Exception:
        logger.error("Error while fetching session key ", exc_info=True)

    return session_key


def get_splunkd_info():
    splunkd_info = urlparse(get_splunkd_uri())
    return splunkd_info


class ConfMigration:
    def __init__(self):
        self._failed_proxy_migration = False
        self._failed_tenants_migration = set()

    def _get_legacy_password(self, name):
        pwd = self.client.storage_passwords[name]
        clear_password = pwd.content.clear_password
        return pwd, clear_password

    def send_notification(self, message):
        """Sends the notification to Splunk UI.

        Args:
            name (str): Name of the message
            message (str): Value of the message
            severity (str): Message severity. info/warn/error
        """
        name = f"Secrets Migration Failed For Splunk Add-on for Microsoft Office 365 {time.time()}"
        url: str = f"{self._splunkd_info.scheme}://{self._splunkd_info.hostname}:{self._splunkd_info.port}/services/messages"
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {self._session_key}",
        }
        payload = {"name": name, "value": message, "severity": "error"}
        response = requests.post(url, data=payload, headers=headers, verify=False)
        if response.status_code != 201:
            logger.warn("Failed to send UI notification for Secret Migration Failures")

    def migrate_proxy(self):
        conf_mgr = ConfManager(
            self._session_key,
            APP_NAME,
            scheme=self._splunkd_info.scheme,
            host=self._splunkd_info.hostname,
            port=self._splunkd_info.port,
            realm=f"__REST_CREDENTIAL__#{APP_NAME}#configs/conf-{SETTINGS_CONF_FILE_NAME}",
        )
        try:
            conf_file = conf_mgr.get_conf(SETTINGS_CONF_FILE_NAME)
        except Exception as e:
            logger.info(
                f"Settings conf file does not exist. Hence skipping the proxy migration"
            )
            return

        stanza_name = "proxy"
        stanza = conf_file.get(stanza_name, only_current_app=True)

        if not stanza.get("host"):
            logger.info(f"No proxy configured hence skipping the migration")
            return

        is_conf_migrated = stanza.get("is_conf_migrated") or 0
        if is_conf_migrated:
            logger.info(f"Proxy is already migrated hence skipping the migration")
            return

        # reversing the disabled field as field name proxy_enabled will be used instead for the configuration
        stanza["proxy_enabled"] = not sutils.is_true(stanza["disabled"])

        pwd_proxy = None
        clear_password = None
        proxy_password = stanza.get("password")
        if proxy_password and proxy_password == "********":
            legacy_password_stanza = f"{APP_NAME}_{stanza_name}_password"
            try:
                pwd_proxy, clear_password = self._get_legacy_password(
                    legacy_password_stanza
                )
                stanza["password"] = clear_password
            except Exception as e:
                self._failed_proxy_migration = True
                logger.error(
                    f"Error while fetching proxy password. Please re-configure the proxy password",
                    exc_info=True,
                )

        fields_to_include = [
            "host",
            "port",
            "username",
            "password",
            "proxy_enabled",
        ]
        new_stanza = {key: stanza[key] for key in fields_to_include if key in stanza}
        new_stanza["is_conf_migrated"] = 1
        conf_file.update(stanza_name, new_stanza, ["password"])
        if pwd_proxy:
            pwd_proxy.delete()
        logger.info("Proxy conf migration completed successfully")

    def migrate_tenants(self):
        conf_mgr = ConfManager(
            self._session_key,
            APP_NAME,
            scheme=self._splunkd_info.scheme,
            host=self._splunkd_info.hostname,
            port=self._splunkd_info.port,
            realm=f"__REST_CREDENTIAL__#{APP_NAME}#configs/conf-{TENANTS_CONF_FILE_NAME}",
        )

        try:
            conf_file = conf_mgr.get_conf(TENANTS_CONF_FILE_NAME)
        except Exception as e:
            logger.info(
                f"Tenants conf file does not exist. Hence skipping the tenants migration"
            )
            return

        stanzas = conf_file.get_all(only_current_app=True)
        fields_to_include = [
            "endpoint",
            "tenant_id",
            "client_id",
            "client_secret",
            "cloudappsecuritytoken",
            "cas_portal_url",
            "cas_portal_data_center",
        ]
        is_migrated = False
        for stanza_name, stanza in list(stanzas.items()):
            is_conf_migrated = stanza.get("is_conf_migrated") or 0
            if is_conf_migrated:
                logger.info(f"Skipping the already migrated tenant={stanza_name}")
                continue

            logger.info(f"Migration started for tenant={stanza_name}")

            pwd_client_secret = None
            pwd_cloudappsecuritytoken = None

            client_secret = stanza.get("client_secret")
            cloudappsecuritytoken = stanza.get("cloudappsecuritytoken")

            if client_secret and client_secret == "********":
                legacy_clientsecret_stanza = f"{APP_NAME}_{stanza_name}_client_secret"
                try:
                    pwd_client_secret, clear_client_secret = self._get_legacy_password(
                        legacy_clientsecret_stanza
                    )
                    stanza["client_secret"] = clear_client_secret
                except Exception as e:
                    self._failed_tenants_migration.add(stanza_name)
                    logger.error(
                        f"Error while fetching client_secret for tenant={stanza_name}. Please re-configure 'Client Secret'",
                        exc_info=True,
                    )

            if cloudappsecuritytoken and cloudappsecuritytoken == "********":
                legacy_cloudappsecuritytoken_stanza = (
                    f"{APP_NAME}_{stanza_name}_cloudappsecuritytoken"
                )
                try:
                    (
                        pwd_cloudappsecuritytoken,
                        clear_cloudappsecuritytoken,
                    ) = self._get_legacy_password(legacy_cloudappsecuritytoken_stanza)
                    stanza["cloudappsecuritytoken"] = clear_cloudappsecuritytoken
                except Exception as e:
                    self._failed_tenants_migration.add(stanza_name)
                    logger.error(
                        f"Error while fetching cloudappsecuritytoken for tenant={stanza_name}. Please re-configure 'Cloud App Security Token'",
                        exc_info=True,
                    )

            new_stanza = {
                key: stanza[key] for key in fields_to_include if key in stanza
            }
            new_stanza["is_conf_migrated"] = 1
            conf_file.update(
                stanza_name, new_stanza, ["client_secret", "cloudappsecuritytoken"]
            )
            if pwd_client_secret:
                pwd_client_secret.delete()
            if pwd_cloudappsecuritytoken:
                pwd_cloudappsecuritytoken.delete()
            is_migrated = True
            logger.info(f"Migration completed for tenant={stanza_name}")

        if is_migrated:
            logger.info("Tenants conf migration completed successfully")

    def run(self):
        logger.info("Conf migration started")

        self._session_key = get_session_key()
        self._splunkd_info = get_splunkd_info()

        self.client = SplunkRestClient(
            self._session_key,
            APP_NAME,
            scheme=self._splunkd_info.scheme,
            host=self._splunkd_info.hostname,
            port=self._splunkd_info.port,
        )

        logger.info("Proxy conf migration started")
        try:
            self.migrate_proxy()
        except Exception as e:
            logger.error(f"Error while migrating proxy. Error={e}", exc_info=True)
            self._failed_proxy_migration = True

        is_tenant_failed = False
        logger.info("Tenants password(s) conf migration started")
        try:
            self.migrate_tenants()
        except Exception as e:
            is_tenant_failed = True
            logger.error(f"Error while migrating tenants. Error={e}", exc_info=True)

        if (
            self._failed_proxy_migration
            or is_tenant_failed
            or self._failed_tenants_migration
        ):
            failed = []
            if self._failed_proxy_migration:
                failed.append("Proxy")
            if is_tenant_failed:
                failed.append("Tenants")
            elif self._failed_tenants_migration:
                failed.append(
                    f"Tenants: ({','.join(str(fsm) for fsm in self._failed_tenants_migration)})"
                )

            message = f"Splunk Add-on for Microsoft Office 365: Secrets migration failed for '{', '.join(f for f in failed)}'. Please reconfigure."
            self.send_notification(message)

        logger.info("Conf migration completed")


if __name__ == "__main__":
    conf_migration = ConfMigration()
    try:
        conf_migration.run()
    except Exception as e:
        logger.error(f"Error while migrating the conf. Error={e}", exc_info=True)
        conf_migration.send_notification(
            f"Splunk Add-on for Microsoft 365: Secrets migration failed for 'Proxy, Tenants'. Please reconfigure."
        )

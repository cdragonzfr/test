#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import urllib.parse
import requests
import time
from splunksdc import logging
from splunksdc.config import (
    StanzaParser,
    StringField,
    BooleanField,
    LogLevelField,
)
from splunk_ta_o365 import set_log_level


logger = logging.get_module_logger()


class Proxy:
    @staticmethod
    def _wipe(settings):
        params = vars(settings).copy()
        del params["password"]
        return params

    @classmethod
    def load(cls, config):
        conf_name = "splunk_ta_o365_settings"
        stanza = "proxy"
        content = None
        retry = 0
        while True:
            config.clear(conf_name, stanza=stanza, virtual=True)
            content = config.load(conf_name, stanza=stanza, virtual=True)
            parser = StanzaParser(
                [
                    BooleanField("proxy_enabled", rename="enabled"),
                    StringField("host"),
                    StringField("port"),
                    StringField("username"),
                    StringField("password"),
                    BooleanField("is_conf_migrated"),
                ]
            )
            settings = parser.parse(content)

            # checking host if proxy is configured or not, if not, then skip checking conf_migrated flag
            if not settings.host or settings.is_conf_migrated:
                break
            if retry == 4:
                break
            retry += 1
            logger.info("Waiting for Proxy Conf migration to be completed")
            time.sleep(60)

        logger.info("Load proxy settings success.", **cls._wipe(settings))
        return cls(settings)

    def __init__(self, settings):
        self._settings = settings

    def _make_url(self, scheme):
        settings = self._settings
        endpoint = f"{settings.host}:{settings.port}"
        auth = None
        if settings.username and len(settings.username) > 0:
            auth = urllib.parse.quote(settings.username.encode(), safe="")
            if settings.password and len(settings.password) > 0:
                auth += ":"
                auth += urllib.parse.quote(settings.password.encode(), safe="")

        if auth:
            endpoint = auth + "@" + endpoint

        url = scheme + "://" + endpoint
        return url

    def create_requests_session(self):
        session = requests.Session()
        if self._settings.enabled:
            server_uri = self._make_url("http")
            session.proxies.update({"http": server_uri, "https": server_uri})
        return session


class Logging:
    @classmethod
    def load(cls, config):
        content = config.load("splunk_ta_o365_settings", stanza="logging")
        parser = StanzaParser([LogLevelField("log_level", default="WARNING")])
        settings = parser.parse(content)
        return cls(settings)

    def __init__(self, settings):
        self._settings = settings

    def apply(self):
        set_log_level(self._settings.log_level)

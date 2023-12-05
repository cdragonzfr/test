#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import calendar
import datetime
import json
import logging
import math
import os
import os.path as op
import time
import urllib.error
import urllib.parse
import urllib.request
from splunktaucclib.common.log import set_log_level

import mscs_consts
from solnlib.splunkenv import get_splunkd_uri  # pylint: disable=import-error
from splunk import admin, clilib, rest  # pylint: disable=import-error

from solnlib import (  # isort: skip # pylint: disable=import-error
    conf_manager,
    time_parser,
    utils,
)

from codecs import (  # isort: skip
    BOM_UTF8,
    BOM_UTF16_BE,
    BOM_UTF16_LE,
    BOM_UTF32_BE,
    BOM_UTF32_LE,
)

g_time_parser = None


def _make_log_file_path(filename):
    """
    The replacement for make_splunkhome_path in splunk.appserver.mrsparkle.lib.util
    Importing the package above will corrupted the sys.path.
    """

    home = os.environ.get("SPLUNK_HOME", "")
    return op.join(home, "var", "log", "splunk", filename)


class SessionKeyProvider(admin.MConfigHandler):
    def __init__(self):
        self.session_key = self.getSessionKey()


def get_proxy_info_from_endpoint():
    """Get the proxy details from the endpoint.

    :return: Dictionary containing details of proxy
    """

    splunkd_uri = get_splunkd_uri()
    rest_endpoint = (
        splunkd_uri
        + "/servicesNS/nobody/Splunk_TA_microsoft-cloudservices/splunk_ta_mscs_settings/proxy?--cred--=1&"
        "output_mode=json"
    )

    session_key = SessionKeyProvider().session_key
    response, content = rest.simpleRequest(
        rest_endpoint, sessionKey=session_key, method="GET", raiseAllErrors=True
    )
    proxy_settings = json.loads(content)["entry"][0]["content"]

    # If proxy username is available, Replace special character in %xx format
    if proxy_settings.get("proxy_username"):
        proxy_settings["proxy_username"] = urllib.parse.quote(
            proxy_settings["proxy_username"], encoding="utf-8", safe=""
        )

    # If proxy password is available, Replace special character in %xx format
    if proxy_settings.get("proxy_password"):
        proxy_settings["proxy_password"] = urllib.parse.quote(
            proxy_settings["proxy_password"], encoding="utf-8", safe=""
        )

    return proxy_settings


def make_proxy_url(host, port, user, password, protocol="http"):
    proxy_url = "{host}:{port}".format(host=host, port=port)
    auth = None
    if user and len(user) > 0:
        auth = user
        if password and len(password) > 0:
            auth += ":" + password
    if auth:
        proxy_url = auth + "@" + proxy_url
    proxy_url = protocol + "://" + proxy_url
    return proxy_url


def get_logger(log_name, log_level=logging.INFO):
    """Return the logger.

    :param log_name: Name for the logger
    :param log_level: Log level
    :return: logger object
    """

    log_file = _make_log_file_path("{}.log".format(log_name))

    log_dir = op.dirname(log_file)

    if not op.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger(log_name)

    handler_exists = any(
        [True for item in logger.handlers if item.baseFilename == log_file]
    )

    if not handler_exists:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, mode="a", maxBytes=25000000, backupCount=5
        )
        format_string = (
            "%(asctime)s %(levelname)s pid=%(process)d tid=%(threadName)s file=%(filename)s:%("
            "funcName)s:%(lineno)d | %(message)s"
        )
        formatter = logging.Formatter(format_string)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(log_level)
        logger.propagate = False

    return logger


def get_conf_file_info(session_key, conf_file_name):
    cfm = conf_manager.ConfManager(
        session_key,
        "Splunk_TA_microsoft-cloudservices",
        realm="__REST_CREDENTIAL__#Splunk_TA_microsoft-cloudservices#configs/conf-{}".format(
            conf_file_name
        ),
    )

    conf = cfm.get_conf(conf_file_name)
    configs = conf.get_all()
    return configs


def check_account_isvalid(confInfo, session_id, account_type):
    """
    Check whether each account has been reconfigured or not
    """
    if account_type == "storage":
        conf_file_name = "mscs_storage_accounts"
        credential_field = "account_secret"
    elif account_type == "azure":
        conf_file_name = "mscs_azure_accounts"
        credential_field = "client_secret"
    else:
        raise ValueError(
            "Invalid credential_field: Possible values are ['storage', 'azure']"
        )

    try:
        cfm = conf_manager.ConfManager(
            session_id,
            "Splunk_TA_microsoft-cloudservices",
            realm="__REST_CREDENTIAL__#Splunk_TA_microsoft-cloudservices#configs/conf-{}".format(
                conf_file_name
            ),
        )
        # Get Conf object of account settings
        conf = cfm.get_conf(conf_file_name)
        # Get account stanza from the settings
        account_configs = conf.get_all()
        for accountStanzaKey, accountStanzaValue in list(confInfo.items()):
            account_name = (
                accountStanzaValue.get("account")
                if "account" in accountStanzaValue
                else accountStanzaKey
            )
            if (
                account_name in account_configs
                and account_configs[account_name].get(credential_field) != "*" * 8
            ):
                accountStanzaValue["isvalid"] = "true"
            else:
                accountStanzaValue["isvalid"] = "false"
    except conf_manager.ConfManagerException:
        # For fresh addon account conf file will not exist so handling that exception
        pass


def check_account_secret_isvalid(confInfo, session_id, account_type, storage_account):
    """
    Check whether each secret has been valid or not
    """

    if account_type == "storage":
        conf_file_name = "mscs_storage_accounts"
        credential_field = "account_secret"
    else:
        raise ValueError("Invalid credential_field: Possible values are ['storage']")

    try:
        cfm = conf_manager.ConfManager(
            session_id,
            "Splunk_TA_microsoft-cloudservices",
            realm="__REST_CREDENTIAL__#Splunk_TA_microsoft-cloudservices#configs/conf-{}".format(
                conf_file_name
            ),
        )
        # Get Conf object of account settings
        conf = cfm.get_conf(conf_file_name)
        # Get account stanza from the settings
        account_configs = conf.get_all()
        if (
            account_configs[storage_account[0]].account_secret_type == "0"
        ):  # None Secret
            return False
        return True

    except conf_manager.ConfManagerException:
        # For fresh addon account conf file will not exist so handling that exception
        pass


def timestamp_to_localtime(session_key, timestamp):
    global g_time_parser
    if not g_time_parser:
        g_time_parser = time_parser.TimeParser(session_key)
    utc_str = timestamp_to_utc(timestamp)
    local_str = g_time_parser.to_local(utc_str)
    return local_str[0:19] + local_str[23:]


def timestamp_to_utc(timestamp):
    utc_time = datetime.datetime.utcfromtimestamp(timestamp)
    return utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_timestr_to_timestamp(utc_timestr):
    timestr_sec_part = utc_timestr[0:19]
    utc_datetime = datetime.datetime.strptime(timestr_sec_part, "%Y-%m-%dT%H:%M:%S")
    sec_part = calendar.timegm(utc_datetime.timetuple())
    remain_part = utc_timestr[20:-1]
    if remain_part:
        nanosecond = int(remain_part) * math.pow(10, 9 - len(remain_part))
        return int(sec_part * 1000000000 + int(nanosecond))
    else:
        return int(sec_part * 1000000000)


def get_30_days_ago_local_time(session_key):
    cur_time = time.time()
    before_time = cur_time - 30 * 24 * 60 * 60
    return timestamp_to_localtime(session_key, before_time)


def decode_ascii_str(ascii_str):
    decoded_str = ""
    len_str = len(ascii_str)
    i = 0
    while i < len_str:
        if ascii_str[i] == ":" and i + 4 < len_str:
            decoded_str += chr(int(ascii_str[i + 1 : i + 5], 16))  # noqa: E203
            i += 5
        else:
            decoded_str += ascii_str[i]
            i += 1
    return decoded_str


BOMS = (
    (BOM_UTF8, "UTF-8"),
    (BOM_UTF32_BE, "UTF-32-BE"),
    (BOM_UTF32_LE, "UTF-32-LE"),
    (BOM_UTF16_BE, "UTF-16-BE"),
    (BOM_UTF16_LE, "UTF-16-LE"),
)


def check_bom(data):
    # http://unicodebook.readthedocs.io/guess_encoding.html
    return [encoding for bom, encoding in BOMS if data.startswith(bom)]


def proxy_from_config(proxy_config):
    if not proxy_config or not utils.is_true(proxy_config.get("proxy_enabled")):
        return None
    host = proxy_config.get(mscs_consts.PROXY_URL)
    port = proxy_config.get(mscs_consts.PROXY_PORT)
    user = proxy_config.get(mscs_consts.PROXY_USERNAME)
    password = proxy_config.get(mscs_consts.PROXY_PASSWORD)

    if not all((host, port)):
        raise ValueError("Proxy host={} or port={} is invalid".format(host, port))

    if user and password:
        user = urllib.parse.quote(user, encoding="utf-8", safe="")
        password = urllib.parse.quote(password, encoding="utf-8", safe="")
    if "://" in host:
        host = host.split("://", 1)[1]
    return host, port, user, password


def get_schema_file_path(filename):
    return op.join(op.dirname(op.abspath(__file__)), filename)


def setup_log_level():
    """
    Set the log level of the logging
    """
    cfm = clilib.cli_common.getConfStanza("splunk_ta_mscs_settings", "logging")
    log_level = cfm.get("agent")
    set_log_level(log_level)

#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import logging
import os
import time
from datetime import datetime

from dateutil.parser import parse
from dateutil.tz import tzutc
from functools import wraps

_EPOCH = datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=tzutc())


def string_to_timestamp(text):
    dt = parse(text)
    elapse = dt - _EPOCH
    return elapse.total_seconds()


def _make_log_file_path(filename):
    """
    The replacement for make_splunkhome_path in splunk.appserver.mrsparkle.lib.util
    Importing the package above will corrupted the sys.path.
    """

    home = os.environ.get("SPLUNK_HOME", "")
    return os.path.join(home, "var", "log", "splunk", filename)


def get_logger(log_name, log_level=logging.INFO):
    """Return the logger.
    :param log_name: Name for the logger
    :param log_level: Log level
    :return: logger object
    """

    log_file = _make_log_file_path("{}.log".format(log_name))
    log_dir = os.path.dirname(log_file)

    if not os.path.exists(log_dir):
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
            "funcName)s:%(lineno)d | %(message)s "
        )
        formatter = logging.Formatter(format_string)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(log_level)
        logger.propagate = False

    return logger


def time_taken(logger: callable, message: str, debug: bool = True) -> callable:
    """
    Calculate time consumed by the given func
    Taking logger as param to provide flexibility

    Args:
        logger (callable): logger object
        message (str): Message to log
        debug (bool, optional): whether to debug the log. Defaults to True.

    Returns:
        callable: object
    """

    def time_it(func: callable) -> callable:
        @wraps(func)
        def _wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            total_time = round(end_time - start_time, 4)
            if debug:
                logger.debug(message, time_taken=total_time)
            else:
                logger.info(message, time_taken=total_time)
            return result

        return _wrapper

    return time_it


def time_to_string(format: str, timestamp: datetime) -> str:
    """
    Convert the datetime obj to string

    Args:
        format (str): format to be converted
        timestamp (datetime): timestamp

    Returns:
        str: converted timestamp
    """
    return timestamp.strftime(format)


def string_to_time(format: str, timestamp: str) -> datetime:
    """
    Convert the string obj to datetime

    Args:
        timestamp (str): time to be converted

    Returns:
        datetime: converted timestamp
    """
    return datetime.strptime(timestamp, format)

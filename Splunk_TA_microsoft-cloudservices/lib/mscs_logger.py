#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import logging


class PrefixedLoggerAdapter(logging.LoggerAdapter):
    """
    The logger adapter wraps a logger instance and padding a log prefix for
    every log message.
    """

    def __init__(self, logger, prefix):
        super(PrefixedLoggerAdapter, self).__init__(logger, {})
        self.prefix = prefix

    def process(self, msg, kwargs):
        return "%s %s" % (self.prefix, msg), kwargs


def logger_for(log_prefix):
    """
    Wrap the default logger instance with a prefix.

    :param log_prefix: The prefix to be inserted to the front of log.
    :return: A PrefixedLoggerAdapter
    """
    from splunktaucclib.common.log import logger

    return PrefixedLoggerAdapter(logger, log_prefix)

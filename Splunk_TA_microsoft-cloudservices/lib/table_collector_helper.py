#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import calendar
import datetime

import iso8601
import splunktaucclib.common.log as stulog

_WAD_TABLES = [
    "WadLogsTable",
    "WADDiagnosticInfrastructureLogsTable",
    "WADDirectoriesTable",
    "WADPerformanceCountersTable",
    "WADWindowsEventLogsTable",
]


def _is_wad_table(table_name):
    upper_table_name = table_name.upper()
    return any(tb.upper() == upper_table_name for tb in _WAD_TABLES)


def is_websitesapp_table(table_name):
    return table_name.lower().startswith("websitesapplogs")


def _recognize_datetime(date_string):
    # We need support two kind formats:
    # 2017-06-13T00:00:00Z 2017-06-12T00:00:00+08:00
    date_tuple = iso8601.parse_date(date_string).utctimetuple()
    return datetime.datetime.utcfromtimestamp(calendar.timegm(date_tuple))


def _timestamp_to_ticks_count(timestamp, offset=0):
    stulog.logger.debug("Calculating ticks count from %s", timestamp)
    try:
        t = _recognize_datetime(timestamp)
        timestamp = int(
            (t - datetime.datetime(1, 1, 1, 0, 0, 0)).total_seconds() * 10000000
        )
        return "0%s" % (timestamp + offset)
    except Exception as e:
        stulog.logger.warning(
            "Calculating ticks count from %s failed: %s", timestamp, str(e)
        )
    return None


def _timestamp_to_datetime(timestamp, hour_offset=0):
    stulog.logger.debug("Parsing datetime from %s", timestamp)
    try:
        t = _recognize_datetime(timestamp)
        t = t + datetime.timedelta(hours=hour_offset)
        return t.strftime("%Y%m%d%H")
    except Exception as e:
        stulog.logger.warning("Parsing datetime from %s failed: %s", timestamp, str(e))
    return None


def generate_partition_key(table_name, start_time, end_time):
    if _is_wad_table(table_name):
        # 15 minutes earlier from now
        start = _timestamp_to_ticks_count(start_time, -9000000000)
        # Don't need offset cause the actual partition key of events in
        # range [start_time, end_time) must less than ticks count of end_time.
        end = _timestamp_to_ticks_count(end_time)
        return start, end
    elif is_websitesapp_table(table_name):
        # 1 hour earlier from now
        start = _timestamp_to_datetime(start_time, -1)
        end = _timestamp_to_datetime(end_time)
        return start, end
    else:
        # For other tables, we don't know their partition key
        # generation mechanism now.
        return None, None

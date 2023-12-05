#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# splunk
from builtins import object

SESSION_KEY = "session_key"
CHECKPOINT_DIR = "checkpoint_dir"

# global_settings
GLOBAL_SETTINGS = "global_settings"

# mscs_settings
PERFORMANCE_TUNING_SETTINGS = "performance_tuning_settings"
WORKER_THREADS_NUM = "worker_threads_num"

QUERY_END_TIME_OFFSET = "query_end_time_offset"
EVENT_CNT_PER_ITEM = "event_cnt_per_item"

LIST_TABLES_PAGE_SIZE = "list_tables_page_size"
QUERY_ENTITIES_PAGE_SIZE = "query_entities_page_size"

LIST_BLOBS_PAGE_SIZE = "list_blobs_page_size"
GET_BLOB_BATCH_SIZE = "get_blob_batch_size"

LIST_MANAGEMENT_EVENTS_PAGE_SIZE = "list_management_events_page_size"

# proxy
PROXY = "proxy"
PROXY_URL = "proxy_url"
PROXY_PORT = "proxy_port"
PROXY_USERNAME = "proxy_username"
PROXY_PASSWORD = "proxy_password"
PROXY_ENABLED = "proxy_enabled"

# inputs
STANZA_NAME = "stanza_name"
TABLE_LIST = "table_list"
TABLE_NAME = "table_name"
START_TIME = "start_time"

CONTAINER_NAME = "container_name"
BLOB_LIST = "blob_list"
LOG_TYPE = "log_type"
GUIDS = "guids"
APPLICATION_INSIGHTS = "application_insights"
EXCLUDE_BLOB_LIST = "exclude_blob_list"
BLOB_NAME = "blob_name"
INCLUDE_SNAPSHOTS = "include_snapshots"
SNAPSHOTS_START_TIME = "snapshots_start_time"
SNAPSHOTS_END_TIME = "snapshots_end_time"
SNAPSHOT = "snapshot"
BLOB_TYPE = "blob_type"
BLOB_MODE = "blob_mode"
DECODING = "decoding"
LINE_BREAKER = "line_breaker"
BATCH_SIZE = "batch_size"
BLOB_CREATION_TIME = "blob_creation_time"
ETAG = "etag"
PREFIX = "prefix"
CHUNK_SIZE = 100

SUBSCRIPTION_ID = "subscription_id"
RESOURCE_TYPE = "resource_type"
RESOURCE_GROUP_LIST = "resource_group_list"

INDEX = "index"
SOURCETYPE = "sourcetype"

# checkpoint
QUERY_START_TIME = "query_start_time"
QUERY_END_TIME = "query_end_time"
PAGE_LINK = "page_link"
CUR_PARTITIONKEY = "cur_partitionkey"
CUR_ROWKEY = "cur_rowkey"
CUR_TIMESTAMP = "cur_timestamp"
STATUS = "status"

RECEIVED_BYTES = "received_bytes"
LAST_MODIFIED = "last_modified"
IS_COMPLETED = "is_completed"
CODESET = "codeset"

CUR_INDEX = "cur_index"

# storage account
ACCOUNT = "account"
ACCOUNTS = "accounts"
ACCOUNT_NAME = "account_name"
ACCOUNT_SECRET_TYPE = "account_secret_type"
ACCOUNT_SECRET = "account_secret"
ACCOUNT_CLASS_TYPE = "account_class_type"

# azure account
CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"
TENANT_ID = "tenant_id"

# api_settings
API_SETTINGS = "api_settings"
URL = "url"
INSTANCE_VIEW_URL = "instance_view_url"
API_VERSION = "api_version"
STANDARD_HOSTNAME = "management.azure.com"
GOVCLOUD_HOSTNAME = "management.usgovcloudapi.net"
PUBLISHER_ID = "2ed28a74-1f6f-4829-8530-fe359c77d35c"

AUDIT = "audit"


class CheckpointStatusType(object):
    CUR_PAGE_ONGOING = "cur_page_ongoing"

    CUR_PAGE_DONE = "cur_page_done"

    ALL_DONE = "all_done"

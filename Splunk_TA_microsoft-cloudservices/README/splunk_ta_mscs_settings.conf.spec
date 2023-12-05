##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
##

[proxy]
proxy_enabled = <boolean> bool value indicate if the proxy is enabled or not
proxy_rdns = <string> DNS resolution of the proxy
proxy_type = <string> type of proxy, like http, http_no_tunnel, socks4, socks5
proxy_password = <string> password of proxy account
proxy_port = <integer> port of proxy
proxy_url = <string> proxy host
proxy_username = <string> user name of proxy account

[logging]
agent = <string> the loglevel of TA

[performance_tuning_settings]
worker_threads_num = <integer> Worker Threads Count
query_entities_page_size = <integer> Page Size of Page Entries
event_cnt_per_item = <integer> Total events per items
query_end_time_offset = <integer> Query End Time offset
get_blob_batch_size = <integer> Blob Batch size
http_timeout = <integer> Http timeout

[advanced]
delete_storageblob_ckpt_files = <string> Allow Storage Blob input checkpoint files deletion from the splunk environment

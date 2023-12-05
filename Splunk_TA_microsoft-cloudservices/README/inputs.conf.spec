##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
##
[mscs_storage_blob://<name>]
python.version = {python3}
description = <string> description of the input type
account = <string> the account stanza name in mscs_storage_accounts.conf
container_name = <string> the container name under the storage account
prefix = <string> input will only collect the data from the blobs whose names begin with specified prefix
blob_list = <string>  the blob list from which the data should be collected
collection_interval = <integer> the interval for the input, in seconds
exclude_blob_list = <string> the blob list from which the data should not be collected
blob_mode = <string> blob mode of the api (default is random)
is_migrated = [0|1] Whether checkpoint has been migrated or not.
decoding = <string> the character set of the blobs. e.g UTF-8, UTF-32, etc.
log_type = <string> Filters the results to return only blobs whose names begin with the specified prefix.
guids = <string> List the individual comma separated GUIDs
application_insights = <checkbox> Blob collection will be changed if this is set to true
index = <string> the index of the fetched data
sourcetype = <string> the sourcetype of the fetched data
blob_input_help_link = <string> URL for the link on which you want to redirect

[mscs_storage_table://<name>]
python.version = {python3}
description = <string> description of the input type
account = <string> the account stanza name in mscs_storage_accounts.conf
storage_table_type = <string> storage_table or virtual_machine_metrics
table_list = <string> the names of the tables to query
start_time = <string> the time to start querying from storage api
collection_interval = <integer> the interval for the input, in seconds
index = <string> the index of the fetched data
sourcetype = <string> the sourcetype of the fetched data
storage_input_help_link = <string> URL for the link on which you want to redirect
storage_virtual_metrics_input_help_link = <string> URL for the link on which you want to redirect

[mscs_azure_resource://<name>]
python.version = {python3}
description = <string> description of the input type

[mscs_azure_audit://<name>]
python.version = {python3}
description = <string> description of the input type

[mscs_azure_event_hub://<name>]
python.version = {python3}
account = <string> the account stanza name in mscs_azure_accounts.conf
event_hub_namespace = <string> The Azure Event Hub Namespace (FQDN)
event_hub_name = <string> The Azure Event Hub Name
consumer_group = <string> The Azure Event Hub Consume Group
blob_checkpoint_enabled = <boolean> bool value indicates if storage blob checkpointing is enabled for Eventhubs
storage_account = <string> Storage Account
container_name = <string> Storage Blob Container name for EventHub checkpoint
max_wait_time = <integer> The maximum interval in seconds that the event processor will wait before processing
max_batch_size = <integer> The maximum number of events that would be retrieved in one batch
event_format_flags = <integer> The bitwise flags that determines the format of output events
use_amqp_over_websocket = <boolean> The switch that allow using AMQP over WebSocket
sourcetype =

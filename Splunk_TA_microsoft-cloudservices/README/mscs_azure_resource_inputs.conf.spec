##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
##

[<name>]
description = <string> description of the input type
account = <string> the account stanza name in mscs_azure_accounts.conf
subscription_id = <string> query the management events belong to the subscription
resource_type = <string> the api stanza name in mscs_api_settings.conf
resource_group_list = <string> query the resources belong to the resource group list
interval = <integer> the interval for the input, in seconds
index = <string> the index of the fetched data
resource_help_link = <string> URL for the link on which you want to redirect

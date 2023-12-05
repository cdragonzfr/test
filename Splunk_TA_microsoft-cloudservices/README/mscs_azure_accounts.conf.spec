##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
##

[<account_stanza_name>]
client_id = <string> the client id which is automatically generated when registering with Azure AD
client_secret = <string> the password for client id
tenant_id = <string> the UUID which point to the AD containing your application
account_class_type = <integer> should be 1 or 2. 1 for Azure Public Cloud, 2 for Azure Government Cloud

#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import json
import hashlib

# Non-report endpoint content types of the graph inputs
NON_REPORT_CONTENT_TYPES: list = [
    "auditlogs.signins",
    "serviceannouncement.messages",
    "serviceannouncement.issues",
]


def values_parser(content):
    """Method is used to load the Graph API response

    Args:
        content (Response Object): it will contain the API response

    Returns:
        tuple: response data and nextLink URL from the API response
    """
    items = json.loads(content)
    return items.get("value"), items.get("@odata.nextLink")


def make_graph_api_message(data):
    """Method is used to generate the checkpoint key for the Graph API report endpoint inputs.
    Args:
        data (Dict): Unique event of the report endpoint inputs

    Returns:
        str: Encoded data string of the event
    """
    data = json.dumps(data)
    return "key" + hashlib.sha256(data.encode()).hexdigest()


def make_graph_api_by_id_message(data):
    """Method used to get the lagecy checkpoint(file-based) key for the AuditLogs Input.

    Args:
        data (Dict): Unique event of the AuditLogs input

    Returns:
        str: id from the event dictonary
    """
    return data["id"]


def make_graph_api_issue_message(data):
    """Method used to get the lagecy checkpoint(file-based) key for the ServiceAnnouncement Input.

    Args:
        data (Dict): Unique event of the SerivceAnnouncement input

    Returns:
        str: joint string of id and lastModifiedDateTime field from event
    """
    return "{}{}".format(data["id"], data["lastModifiedDateTime"])


def get_endpoint(report):
    """Method used the fetch the endpoint configuration for the data collection.

    Args:
        report (str): Content-Type of the Input.

    Returns:
        dict: return the endpoint configuration based on the content-type.
    """
    endpoint = {}
    # initialize with default values
    endpoint.update(endpoints["default"])
    # overwrite with endpoint values
    endpoint.update(endpoints.get(report, {}))

    # process endpoint
    endpoint["source"] = endpoint.get("source", report)
    endpoint["sourcetype"] = endpoint.get("sourcetype", "o365:graph:api")

    return endpoint


# Endpoint Configuration for All the Graph Inputs
endpoints = {
    "default": {
        "report_name": "get{}(period='D7')",
        "content_parser": values_parser,
        "message_factory": make_graph_api_message,
    },
    "serviceAnnouncement.messages": {
        "params": {
            "$filter": "lastModifiedDateTime gt {} and lastModifiedDateTime le {}",
            "$orderby": "lastModifiedDateTime ASC",
        },
        "source": "ServiceAnnouncement.Messages",
        "sourcetype": "o365:service:updateMessage",
        "path": "/v1.0/admin/serviceAnnouncement/messages",
        "message_factory": make_graph_api_issue_message,
        "collection_name": "splunk_ta_o365_ServiceAnnouncement",
        "query_field": "lastModifiedDateTime",
        "look_back": 2,
    },
    "serviceAnnouncement.issues": {
        "params": {
            "$filter": "lastModifiedDateTime gt {} and lastModifiedDateTime le {}",
            "$orderby": "lastModifiedDateTime ASC",
        },
        "source": "ServiceAnnouncement.Issues",
        "sourcetype": "o365:service:healthIssue",
        "path": "/v1.0/admin/serviceAnnouncement/issues",
        "message_factory": make_graph_api_issue_message,
        "collection_name": "splunk_ta_o365_ServiceAnnouncement",
        "query_field": "lastModifiedDateTime",
        "look_back": 2,
    },
    "AuditLogs.SignIns": {
        "params": {
            "$filter": "createdDateTime ge {} and createdDateTime le {}",
            "$orderby": "createdDateTime ASC",
        },
        "path": "/v1.0/auditLogs/signIns",
        "message_factory": make_graph_api_by_id_message,
        "collection_name": "splunk_ta_o365_AuditLogs",
        "query_field": "createdDateTime",
        "look_back": 1,
    },
}

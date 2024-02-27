#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
# flake8: noqa: E402

import csv
import json
import sys
import time
import urllib.parse
from builtins import str
from collections import namedtuple
from datetime import datetime
from typing import TypeVar, List, Dict

from future import standard_library
from splunk_ta_o365.common.token import (
    CasToken,
    GraphToken,
    O365Token,
    O365TokenProvider,
    MessageTraceToken,
)
from splunk_ta_o365.common.utils import string_to_timestamp, time_taken, time_to_string
from splunksdc import logging

standard_library.install_aliases()

logger = logging.get_module_logger()

_EPOCH = datetime(1970, 1, 1)
Requests = TypeVar("Requests")
Response = TypeVar("Response")

DEFAULT_TIMEOUT: int = 60

"""
    class O365PortalError
    Errors from the API calls made will raise to O365PortalError where the error is processed and business logic
    applied.
"""


class O365PortalError(Exception):
    def __init__(self, response):
        payload: str = ""
        self._status_code = str(response.status_code)
        try:
            payload = response.text
            message = self._status_code + ":" + str(payload)
        except Exception:
            message = self._status_code
        super(O365PortalError, self).__init__(message)
        self._code = None
        try:
            data = json.loads(payload)
            self._code = (
                data["error"]["code"]
                if isinstance(data.get("error"), dict) and data["error"].get("code")
                else None
            )
            self._err_message = (
                data["error"]["message"]
                if isinstance(data.get("error"), dict) and data["error"].get("message")
                else None
            )
        except AttributeError as error:
            # Output the expected AttributeErrors for example 'NoneType' objects.
            logger.exception(
                "There was an error parsing the response body", error=error
            )
        except (KeyError, ValueError):
            # in case server response an invalid json.
            logger.exception("failed to get error code", body=payload)
        except Exception as e:
            logger.exception("failed with exception", error=e)

    def should_retry(self):
        # Never retry if content was already expired.
        # Refer: https://msdn.microsoft.com/en-us/office-365/office-365-management-activity-api-reference
        return self._code != "AF20051"

    def get_error_message(self) -> str:
        """
        Get error message from the exception

        Returns:
            str: error message
        """
        return self._err_message

    def is_time_range_error(self) -> bool:
        """
        Check if error code is of time range issue

        Returns:
            bool: If timerange issue or not
        """
        return self._code == "AF20055"

    def get_status_code(self) -> str:
        """
        Get the status code of the error/response

        Returns:
            str: status code
        """
        return self._status_code


"""
    class O365PortalRegistry
    This sets up the builders for: Login, Management, Graph and Cloud Application Security Portals.
"""


class O365PortalRegistry(object):
    @classmethod
    def load(cls, config):
        builders = {
            "Login": O365LoginPortal,
            "Management": O365ManagementPortal,
            "Graph": GraphApiPortal,
            "CloudAppSecurity": CloudApplicationSecurityApiPortal,
            "MessageTrace": MessageTracePortal,
        }
        content = config.load("splunk_ta_o365_endpoints")
        lookup = dict()
        for realm, endpoints in list(content.items()):
            lookup[realm] = {
                name: url for name, url in list(endpoints.items()) if name in builders
            }
        return cls(lookup, builders)

    def __init__(self, lookup, builders):
        self._lookup = lookup
        self._builders = builders

    def __call__(
        self, name, tenant_id, realm, cas_portal_url=None, cas_portal_data_center=None
    ):
        endpoints = self._lookup.get(realm)
        if not endpoints:
            raise ValueError("{} realm not found".format(realm))
        builder = self._builders.get(name)
        if not builder:
            raise ValueError("Unknown portal class: {}".format(name))
        endpoint = endpoints.get(name)
        if not endpoint:
            raise ValueError("{} endpoint for found".format(name))
        if isinstance(endpoint, str):
            endpoint = endpoint.encode()
        return builder(tenant_id, endpoint)


class O365Portal(object):
    def __init__(
        self, tenant_id, endpoint, cas_portal_url=None, cas_portal_data_center=None
    ):
        self._tenant_id = tenant_id
        self._endpoint = endpoint
        self._cas_portal_url = cas_portal_url
        self._cas_portal_data_center = cas_portal_data_center


"""
    class O365LoginPortal
    def get_token_by_psk - Returns a token object from an API call made to Microsoft for use with the Microsoft
    Management APIs.
    def get_v2_token_by_psk - Returns a token object from an API call made to Microsoft for use with the Microsoft
    Graph APIs.
    def get_cas_token_by_psk - Returns a token object from a pre-shared key associated with the tenant for use with
    Microsoft Cloud Application Security APIs
"""


class O365LoginPortal(O365Portal):
    def __init__(self, tenant_id, endpoint):
        super(O365LoginPortal, self).__init__(tenant_id, endpoint)
        v2path = "{}/oauth2/v2.0/token".format(self._tenant_id)
        self._endpoint = convert(self._endpoint)
        self._v2url = urllib.parse.urljoin(self._endpoint, v2path)

    """
        def get_v2_token_by_psk
        This makes a post call to: /{tenant}/oauth2/v2.0/token to retrieve an access token using the client
        credentials grant method.
        The default scope is set to grant access to microsoft graph api.
        This returns a GraphToken object which contains token metadata.
    """

    def get_v2_token_by_psk(self, client_id, client_secret, resource, session):

        scope = resource + b"/.default"  # resource variable is of type bytes

        response = session.post(
            self._v2url,
            timeout=DEFAULT_TIMEOUT,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
        )
        if response.status_code != 200:
            raise O365PortalError(response)
        content = response.json()
        token = GraphToken(**content)
        logger.info("Acquire access token success.", expires_on=token.expires_on)
        return token

    """
        def get_cas_token_by_psk
        This returns an CasToken object which contains the access token, token type, and the portal url and
        portal datacenter.
    """

    def get_cas_token_by_psk(
        self, cloudappsecuritytoken, cas_portal_url, cas_portal_data_center
    ):

        content = {
            "access_token": cloudappsecuritytoken,
            "token_type": "Token",
            "cas_portal_url": cas_portal_url,
            "cas_portal_data_center": cas_portal_data_center,
        }

        token = CasToken(**content)
        logger.info("Acquire cloud application access token success.")
        return token

    """
        def get_messagetrace_token_by_psk
        This returns an MessageTraceToken object which contains the access token, token type
    """

    def get_messagetrace_token_by_psk(
        self, client_id, client_secret, resource, session
    ):
        scope = resource + b"/.default"

        response = session.post(
            self._v2url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
        )
        if response.status_code != 200:
            raise O365PortalError(response.encode("utf-8"))
        content = response.json()
        token = MessageTraceToken(**content)
        logger.info("Acquire access token success.", expires_on=token.expires_on)
        return token


class O365ManagementPortal(O365Portal):
    def create_token_provider(self, policy):
        return O365TokenProvider(self._endpoint, policy)

    def create_subscription(self, content_type, request_timeout=60):
        return O365Subscription(
            self._tenant_id, self._endpoint, content_type, request_timeout
        )

    def create_service_comms(self):
        return O365ServiceCommunications(self._tenant_id, self._endpoint)


"""
  O365SubscriptionContent:  This namedTuple is used to return the response from the Management Portal API calls.
"""
O365SubscriptionContent = namedtuple(
    "O365SubscriptionContent", ["uri", "id", "expiration"]
)


class O365Subscription(O365Portal):
    def __init__(
        self,
        tenant_id: str,
        endpoint: str,
        content_type: str,
        request_timeout: int = 60,
    ):
        super(O365Subscription, self).__init__(tenant_id, endpoint)
        path = "/api/v1.0/{}/activity/feed".format(self._tenant_id)
        self._endpoint = convert(self._endpoint)
        self._api = urllib.parse.urljoin(self._endpoint, path)
        self._content_type = content_type
        self._request_timeout = request_timeout
        self._time_format = "%Y-%m-%dT%H:%M:%S"

    def get_content_type(self) -> str:
        """
        Get the content type

        Returns:
            str: content type
        """
        return self._content_type

    def _list_available_content(
        self, session: Requests, start_time: datetime = None, end_time: datetime = None
    ) -> Response:
        """
        List the available content for given time

        Args:
            session (Requests): requests session object
            start_time (datetime, optional): start timestamp. Defaults to None.
            end_time (datetime, optional): end timestamp. Defaults to None.

        Returns:
            Response: requests session object
        """
        params = {"contentType": self._content_type}
        if start_time and end_time:
            params.update(
                {
                    "startTime": self._time_to_string(start_time),
                    "endTime": self._time_to_string(end_time),
                }
            )
        return self._perform(session, "GET", "/subscriptions/content", params)

    @time_taken(logger, "Time consumed for listing available contents")
    def list_available_content(
        self, session: Requests, start_time: datetime, end_time: datetime
    ) -> List[Dict]:
        """
        List the available contents with pagination

        Args:
            session (Requests): requests session object
            start_time (datetime): start timestamp
            end_time (datetime): end timestamp

        Returns:
            List[Dict]: contents
        """
        items = []
        response = self._list_available_content(session, start_time, end_time)
        while True:
            array = response.json()
            items.extend(array)
            next_page_url = response.headers.get("NextPageUri")
            if not next_page_url:
                break
            response = self._request(session, "GET", next_page_url)
        return items

    def is_enabled(self, session: Requests) -> bool:
        """
        Check if subscription is enabled

        Args:
            session (Requests): requests session object

        Returns:
            bool: subscription state
        """
        response = self._perform(session, "GET", "/subscriptions/list")
        content = response.json()
        for item in content:
            if self._stricmp(item["contentType"], self._content_type):
                return self._stricmp(item["status"], "enabled")
        return False

    def start(self, session: Requests) -> bool:
        """
        Start the subscription

        Args:
            session (Requests): requests session object

        Returns:
            bool: subscription state
        """
        params = {"contentType": self._content_type}
        response = self._perform(session, "POST", "/subscriptions/start", params)
        content = response.json()
        return self._stricmp(content["status"], "enabled")

    def retrieve_content_blob(self, session: Requests, url: str) -> Response:
        """
        Fetch the content blob based on the url provided

        Args:
            session (Requests): requests session object
            url (str): url to fetch content blob

        Returns:
            Response: requests session object
        """
        return self._request(session, "GET", url)

    def _perform(
        self, session: Requests, method: str, operation: str, kwargs: dict = None
    ) -> Response:
        """
        Make url and prepare for API call

        Args:
            session (Requests): requests session object
            method (str): type of request
            operation (str): api operation
            kwargs (dict, optional): parameters. Defaults to None.

        Returns:
            Response: requests session object
        """
        url = self._api + operation
        return self._request(session, method, url, kwargs)

    def _request(
        self, session: Requests, method: str, url: str, kwargs: dict = None
    ) -> Response:
        """
        Make API call

        Args:
            session (Requests): requests session object
            method (str): type of request
            url (str): url to make api call
            kwargs (dict, optional): params. Defaults to None.

        Raises:
            O365PortalError: Exception

        Returns:
            Response: requests session object
        """
        params = {"PublisherIdentifier": self._tenant_id}
        if kwargs:
            params.update(kwargs)
        logger.debug(
            "Calling management activity API.",
            url=url,
            params=params,
            timeout=self._request_timeout,
        )
        response = session.request(
            method, url, params=params, timeout=self._request_timeout
        )
        status_code = response.status_code
        if status_code != 200 and status_code != 201:
            raise O365PortalError(response)
        return response

    def _time_to_string(self, timestamp: datetime) -> str:
        """
        Convert datetime to string as per the format

        Args:
            timestamp (datetime): timestamp

        Returns:
            str: converted timestamp
        """
        return time_to_string(self._time_format, timestamp)

    def _stricmp(self, str1: str, str2: str) -> bool:
        """
        Compare two strings case-insensitively.

        Args:
            str1 (str): The first string to compare.
            str2 (str): The second string to compare.

        Returns:
            bool: True if the two strings are equal, ignoring case; False otherwise.
        """
        return str1.lower() == str2.lower()


"""
    O365ServiceStatus:  This namedTuple is used to return the response from calls to the Service Status API.
    O365ServiceMessage:  This namedTuple is used to return the response from calls to the Service Message API.
"""
O365ServiceStatus = namedtuple("O365ServiceStatus", ["id", "status_time", "data"])
O365ServiceMessage = namedtuple(
    "O365ServiceMessage", ["id", "last_updated_time", "data"]
)

"""
    class O365ServiceCommunications
    This class is used to make calls to the Microsoft Services Communications API for a specific tenant.
    The base path for calls is: '/api/v1.0/{tenant_id}/ServiceComms/'
    This builds calls for messages, serice status, and historical status
"""


class O365ServiceCommunications(O365Portal):
    def __init__(self, tenant_id, endpoint):
        super(O365ServiceCommunications, self).__init__(tenant_id, endpoint)
        path = "/api/v1.0/{}/ServiceComms/".format(self._tenant_id)
        self._endpoint = convert(self._endpoint)
        self._api = urllib.parse.urljoin(self._endpoint, path)

    @classmethod
    def _make_service_status(cls, data):
        status_time = string_to_timestamp(data["StatusTime"])
        return O365ServiceStatus(
            id=data["Id"],
            status_time=status_time,
            data=json.dumps(data, sort_keys=True),
        )

    @classmethod
    def _make_service_message(cls, data):
        last_updated_time = string_to_timestamp(data["LastUpdatedTime"])
        return O365ServiceMessage(
            id=data["Id"],
            last_updated_time=last_updated_time,
            data=json.dumps(data, sort_keys=True),
        )

    def _make_url(self, operation):
        return self._api + operation

    def historical_status(self):
        return O365ServiceCommsOperation(
            self._make_url("HistoricalStatus"), self._make_service_status
        )

    def current_status(self):
        return O365ServiceCommsOperation(
            self._make_url("CurrentStatus"), self._make_service_status
        )

    def messages(self, last_updated_time):
        _filter = "LastUpdatedTime ge {:%Y-%m-%dT%H:%M:%SZ}".format(last_updated_time)
        return O365ServiceCommsOperation(
            self._make_url("Messages"), self._make_service_message, {"$filter": _filter}
        )


"""
    class O365ServiceCommsOperation:
    This class makes calls to the Office 365 Service Communications APIs.
    The response payload contains and array 'values' that contains the response entries.
    Each response entry is returned to be recorded by the modular inputs event writer.
"""


class O365ServiceCommsOperation(object):
    def __init__(self, url, factory, params=None):
        self._url = url
        self._params = params
        self._factory = factory

    def get(self, session):
        url = self._url
        params = self._params
        logger.debug("Calling service communication API.", url=url, params=params)
        response = session.get(url, params=params)
        if response.status_code != 200:
            raise O365PortalError(response)
        payload = response.json()
        items = payload.get("value", [])
        return [self._factory(item) for item in items]

    @property
    def source(self):
        return self._url


"""
    class GraphApiPortal: Initialize a token provider and graph portal communication classes.
    def create_graph_token_provider:    Gets a GraphToken to use with calls the Microsoft Graph API.
    def get_graph_portal_communications:    Builds calls to the Microsoft Graph API
"""


class GraphApiPortal(O365Portal):
    def create_graph_token_provider(self, policy):
        return O365TokenProvider(self._endpoint, policy)

    def get_graph_portal_communications(self, request_timeout=DEFAULT_TIMEOUT):
        return MSGraphPortalCommunications(
            self._tenant_id, self._endpoint, request_timeout
        )


"""
    class MSGraphPortalCommunications:  Build the calls out to microsoft graph api endpoints and return the results to
    the graph api modular input in a namedtuple titled graphAPIMessage.
    def o365_graph_api_report:   Formats the path: '/v1.0/reports/' appending a report_name.
    def o365_graph_api_audit_report:    Formats the path: '/v1.0/auditLogs/' appending a report_name.
    classmethod _make_o365_graph_api_audit_report:  Builds the namedtuple graphApiMessage and returns it.
    classmethod _make_o365_graph_api_report:  Builds the namedtuple graphApiMessage and returns it. It can take a
    long time to respond so it has a 60 second timeout set.
"""


class MSGraphPortalCommunications(O365Portal):
    def __init__(self, tenant_id, endpoint, request_timeout):
        super(MSGraphPortalCommunications, self).__init__(tenant_id, endpoint)
        self._tenant_id = tenant_id
        self._endpoint = convert(self._endpoint)
        self._request_timeout = request_timeout

    def _make_url(self, path, operation=""):
        return self._endpoint + path + operation

    def o365_graph_api_report(self, report_name, last_updated_time=None):
        path = "/v1.0/reports/"
        return GraphApiReportOperation(
            self._make_url(path, report_name), request_timeout=self._request_timeout
        )

    def o365_graph_api(self, params, content_parser, path):
        return GraphApiAuditOperation(
            self._make_url(path),
            content_parser=content_parser,
            params=params,
            request_timeout=self._request_timeout,
        )


"""
    class CustomThrottleException:
        This class initializes the CustomThrottleException which is used in throttled_get()
"""


class CustomThrottleException(Exception):
    pass


"""
    class GraphApiAuditOperation:
        1. Makes calls to Microsoft Graph API audit and reporting endpoints: '/v1.0/auditLogs/{report_name}/'.
        2. If we encounter the CustomThrottleException based on the HTTP 429 response code, we exponentially increment the sleep time using the throttled_get() method.
        3. If there are results it will split the json response results array into individual messages to be recorded as events.
        4. Calls to AuditLogs.SignIns can take a very long time to respond it is currently set to 60 seconds as 30 seconds proved too short.
"""


class GraphApiAuditOperation(object):
    def __init__(
        self, url, params=None, content_parser=None, request_timeout=DEFAULT_TIMEOUT
    ):
        """This class used to retrieve the data from the portal for Audit and ServiceAnnouncement Endpoint.

        :param url: API endpoint
        :param params: request body parameter
        :param content_parser: used to convert response to events
        """
        self._url = url
        self._params = params
        self._content_parser = content_parser
        self._request_timeout = request_timeout

    def throttled_get(self, session, next_link=None):
        """This method used to get the events from the portal.
        if API throwback CustomThrottleException it will retry for max 5 min and return the empty response.

        :param session: session object
        :param next_link: next_link url
        """
        sleep_time = 30
        while True:
            try:
                return self.get(session, next_link)
            except CustomThrottleException:
                sleep_time = sleep_time * 2
                logger.info("Throttling for {} seconds".format(sleep_time))
                if sleep_time > 300:
                    logger.error("Throttling of 5 minutes failed. Exiting")
                    return [], next_link
                time.sleep(sleep_time)

    def get(self, session, next_link):
        """This method used to get the events from the portal and return the events list.

        :param session: session object
        :param next_link: next_link url
        """
        url = self._url
        params = self._params

        try:
            if not next_link:
                logger.info(
                    "Calling Microsoft Graph API.",
                    url=url,
                    params=params,
                    timeout=self._request_timeout,
                )
                response = session.get(
                    url,
                    params=params,
                    timeout=self._request_timeout,
                    allow_redirects=True,
                )
            else:
                logger.info(
                    "Calling Microsoft Graph API.",
                    next_link=next_link,
                    timeout=self._request_timeout,
                )
                response = session.get(
                    next_link, timeout=self._request_timeout, allow_redirects=True
                )

            # if API throttle limit is reached
            if response.status_code == 429:
                logger.info("Reached API throttle limit")
                message = str(response.status_code) + ":" + str(response.text)
                logger.debug(message)
                raise CustomThrottleException(response)

            # there can be issues if there is an empty body response in some cases
            elif response.status_code != 200:
                raise O365PortalError(response)

            if self._content_parser:
                items, next_link = self._content_parser(response.content)
            else:
                payload = json.loads(response.content)
                items = payload.get("value", [])
                next_link = payload.get("@odata.nextLink")

            return items, next_link

        except AttributeError as error:
            logger.exception(
                "There was an error parsing the response body", error=error
            )
        except CustomThrottleException as throttleError:
            raise throttleError

        except Exception as exception:
            raise exception

    @property
    def source(self):
        return self._url


"""
    class GraphApiReportOperation:
        1. Makes calls to Microsoft Graph API reporting endpoints: '/v1.0/reports/{report_name}'.
        2. If we encounter the CustomThrottleException based on the HTTP 429 response code, we exponentially increment
        the sleep time using the throttled_get() method.
        3. Follow the redirect to the report results to have automatically to download a CSV report.
        4. If there are results then parse the CSV response into a JSON object adding in a timestamp field for
        additional context.
        5. Return the resulting items to the modular input event writer.
"""


class GraphApiReportOperation(object):
    def __init__(self, url, params=None, request_timeout=DEFAULT_TIMEOUT):
        """This class used to retrieve the data from the portal for Report Endpoint.

        :param url: API endpoint
        :param params: request body parameter
        """
        self._url = url
        self._params = params
        self._request_timeout = request_timeout

    @classmethod
    def _convert_csv_to_json(cls, csvResponseData):
        """This class used the convert the API response to json response

        :param csvResponseData: API response
        """
        jsonResponse = []

        # Try and convert the csv response to JSON with keys in the header row.
        try:
            csvReader = csv.DictReader(
                csvResponseData.strip().splitlines(), delimiter=",", quotechar='"'
            )

            for row in csvReader:
                jsonResponse.append(row)

        except Exception as e:
            logger.debug("Error Calling Microsoft Graph API", error=str(e))
            raise

        return jsonResponse

    def throttled_get(self, session):  # jscpd:ignore-start
        """This method used to get the events from the portal.
        if API throwback CustomThrottleException it will retry for max 5 min and return the empty response.

        :param session: session object
        """
        sleep_time = 30
        while True:
            try:
                return self.get(session)
            except CustomThrottleException:
                sleep_time = sleep_time * 2
                logger.info("Throttling for {} seconds".format(sleep_time))
                if sleep_time > 300:
                    logger.error("Throttling of 5 minutes failed. Exiting")
                    return []
                time.sleep(sleep_time)

    def get(self, session):
        """This method used to get the events from the portal and return the events list.

        :param session: session object
        """
        url = self._url

        params = self._params
        logger.info(
            "Calling Microsoft Graph API.",
            url=url,
            params=params,
            timeout=self._request_timeout,
        )
        try:
            response = session.get(
                url,
                params=params,
                timeout=self._request_timeout,
                allow_redirects=True,
            )

            # if API throttle limit is reached
            if response.status_code == 429:
                logger.info("Reached API throttle limit")
                message = str(response.status_code) + ":" + str(response.text)
                logger.debug(message)
                raise CustomThrottleException(response)

            # there can be issues if there is an empty body response in some cases
            elif response.status_code != 200:
                raise O365PortalError(response)

            content = response.content
            if not isinstance(content, str):
                content = content.decode("utf-8")

            # convert the csv data to json format
            response = self._convert_csv_to_json(content)

            return response

        except AttributeError as error:
            logger.exception(
                "There was an error parsing the response body", error=error
            )
            raise
        except Exception as exception:
            raise  # jscpd:ignore-end

    @property
    def source(self):
        return self._url


"""
    class   CloudApplicationSecurityApiPortal:  Initialize cloud Token provider and Cloud App Security Portal
    communication classes.
    def create_cas_token_provider: Gets a token to use to make calls to the cloud application security portal
    def get_cas_portal_communications: Returns CloudApplicationSecurityPortalCommunications which builds/formats
    calls to the cloud application security
"""


class CloudApplicationSecurityApiPortal(O365Portal):
    def create_cas_token_provider(self, policy):
        return O365TokenProvider(self._endpoint, policy)

    def get_cas_portal_communications(self):
        return CloudApplicationSecurityPortalCommunications(
            self._tenant_id, self._endpoint
        )


"""
    casApiMessage: This namedTuple is used to return the response from calls to the Cloud Application Security Messages.
"""
casApiMessage = namedtuple("casApiMessage", ["id", "update_time", "data"])

"""
    class   CloudApplicationSecurityPortalCommunications:
        Build unfiltered calls out to Microsoft Cloud Application Security API endpoints and return the unpaged
        results to the graph api modular input in a namedtuple titled casApiMessage.
        o365_cloud_app_security_call    path = '/api/v1/' + report_name (operation)
        The base url endpoint initialized from the endpoint configuration looks like this:
            CloudAppSecurity = https://tenant_subdomain.tenant_data_center.portal.cloudappsecurity.com
            tenant_subdomain: is replaced with the value of cas_portal_url
            tenant_data_center: is replaced with the value of cas_portal_data_center
        The API calls can use filters but were not implemented.
"""


class CloudApplicationSecurityPortalCommunications(O365Portal):
    def __init__(self, tenant_id, endpoint):
        super(CloudApplicationSecurityPortalCommunications, self).__init__(
            tenant_id, endpoint
        )
        path = "/api/v1/"
        self._tenant_id = tenant_id
        self._endpoint = convert(self._endpoint)
        self._api = urllib.parse.urljoin(self._endpoint, path)

    @classmethod
    def _make_o365_cloud_app_security_call(cls, data):
        return casApiMessage(
            id=data.get("_id", data.get("id")),
            update_time=data.get("timestamp", data.get("lastModified", 0)),
            data=json.dumps(data),
        )

    def _make_url(self, operation):
        return self._api + operation + "/"

    def o365_cloud_app_security_call(
        self, last_updated_time, report_name, cas_portal_url, cas_portal_data_center
    ):
        _filter = last_updated_time
        url = self._make_url(report_name)
        url = url.replace("tenant_subdomain", cas_portal_url)
        url = url.replace("tenant_data_center", cas_portal_data_center)
        return CloudAppSecurityOperation(
            url, self._make_o365_cloud_app_security_call, {"$filter": _filter}
        )


"""
CloudAppSecurityOperation
    Make a call to Microsoft Cloud Application Security API, process the results and return each event in the
    response to the cloud app security modual input event writer.
    If we encounter the CustomThrottleException based on the HTTP 429 response code, we exponentially
    increment the sleep time using the throttled_get() method.
"""


class CloudAppSecurityOperation(object):
    def __init__(self, url, factory, params=None):
        self._url = url
        self._params = params
        self._factory = factory

    def throttled_get(self, session):  # jscpd:ignore-start
        sleep_time = 30
        while True:
            try:
                return self.get(session)
            except CustomThrottleException:
                sleep_time = sleep_time * 2
                logger.info("Throttling for {} seconds".format(sleep_time))
                if sleep_time > 300:
                    logger.error("Throttling of 5 minutes failed. Exiting")
                    return []
                time.sleep(sleep_time)

    def get(self, session):
        url = self._url
        params = self._params

        logger.info("Calling Cloud Application Security API.", url=url, params=params)
        response = session.get(url, timeout=120)

        # if API throttle limit is reached
        if response.status_code == 429:
            logger.info("Reached API throttle limit")
            message = str(response.status_code) + ":" + str(response.text)
            logger.debug(message)
            raise CustomThrottleException(response)

        # there can be issues if there is an empty body response in some cases
        elif response.status_code != 200:
            raise O365PortalError(response)

        payload = json.loads(response.content)
        items = payload.get("data", [])
        return [self._factory(item) for item in items]  # jscpd:ignore-end

    @property
    def source(self):
        return self._url


"""
    class MessageTracePortal: Initialize a token provider.
    def create_messagetrace_token_provider:    Gets a MessageTraceToken to use with calls the Microsoft Reporting API.
"""


class MessageTracePortal(O365Portal):
    def create_messagetrace_token_provider(self, policy):
        return O365TokenProvider(self._endpoint, policy)


def convert(value):
    return value if sys.version_info < (3,) else value.decode("utf-8")

#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import json
import platform
import time
import urllib3
import dateutil.parser
import datetime
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from splunksdc import logging
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import IntegerField, StanzaParser, StringField
from splunk_ta_o365.common.portal import O365PortalError, O365PortalRegistry
from splunk_ta_o365.common.tenant import O365Tenant
from splunk_ta_o365.common.settings import Logging, Proxy
from splunksdc.utils import LogExceptions, LogWith
from splunk_ta_o365.common.checkpoint import KVStoreCheckpoint
from .consts import reportingUrl, baseUrl

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.get_module_logger()

STATUS_CODE_LIST = [429, 500, 502, 503, 504]

"""
    class MessageTraceConsumer
    This class is used to make calls to the Microsoft Reporting API to message trace data and then ingest the events using an eventwriter to splunk.
"""


class MessageTraceConsumer:
    def __init__(self, event_writer, proxy, token, args, name, checkpoint):
        self._event_writer = event_writer
        self._proxy = proxy
        self._token = token
        self._args = args
        self._parameters = self._extract_arguments()
        self._name = name
        self._ckpt = checkpoint

    def _extract_arguments(self):
        parser = StanzaParser(
            [
                StringField("start_date_time"),
                StringField("end_date_time"),
                StringField("input_mode"),
                IntegerField("query_window_size"),
                IntegerField("delay_throttle"),
                IntegerField("interval"),
            ]
        )
        arguments = parser.parse(self._args)
        return arguments

    """
    def _validate_input
    Validation for input parameters
    """

    def _validate_input(self):
        interval = self._parameters.interval
        start_date_time = self._parameters.start_date_time
        end_date_time = self._parameters.end_date_time
        input_mode = self._parameters.input_mode
        query_window_size = self._parameters.query_window_size
        delay_throttle = self._parameters.delay_throttle
        start = None  # Local instance of start date
        end = None  # Local instance of end date

        # Start date checks
        if start_date_time is not None:
            try:
                start = dateutil.parser.parse(start_date_time)
            except Exception as e:
                error_message = "Invalid date format specified for Start Date/Time"
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

        # Index once checks
        if input_mode == "index_once":

            # Make Sure Startdate and Enddate were specified
            if start_date_time is None or end_date_time is None:
                error_message = "Start date/time and End date/time are required for Index Once input"
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

            if start < datetime.datetime.now() - datetime.timedelta(days=10):
                error_message = "Start Date cannot be more than 10 days in the past."
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

            # Make Sure the Interval value is correct
            if interval != -1:
                error_message = "Interval must be -1 for Index Once input"
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

            # Make sure the end date is in correct format
            if end_date_time is not None:
                try:
                    end = dateutil.parser.parse(end_date_time)
                except Exception as e:
                    error_message = "Invalid date format specified for End date/time"
                    logger.error(error_message, exc_info=True, stack_info=True)
                    return False

            # Make sure the end date is after the start date
            if start > end:
                error_message = (
                    "The Start date/time cannot be larger than End date/time"
                )
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

        else:
            # Continuously Monitor checks
            if query_window_size is None or query_window_size < 1:
                error_message = (
                    "Query window size is required and should be atleast 1 minute"
                )
                logger.error(error_message, exc_info=True, stack_info=True)
                return False

            if delay_throttle is None or delay_throttle < 0:
                error_message = "Delay Throttle is required"
                logger.error(error_message, exc_info=True, stack_info=True)
                return False
        return True

    """
    def _collect_events
    Ingest the events based upon selected input_mode
    """

    def _collect_events(self, app):
        input_mode = self._parameters.input_mode
        logger.info("Start Retrieving MessageTrace Data")
        if input_mode == "index_once":
            self._get_events_once()
        else:
            self._get_events_continuous(app)

    def _get_url(self, path):
        url_base = baseUrl
        if "../../" in path:
            path = path.replace("../../", "")
        return url_base + "/" + path

    def _is_https(self, url):
        if url.startswith("https://"):
            return True
        else:
            return False

    def get_start_date(self, checkpoint_key):
        # Try to get a date from the check point first
        date = self._ckpt.get(checkpoint_key)
        if date:
            checkpoint_state = json.loads(date["state"])
        else:
            checkpoint_state = {}

        # If there was a check point date, retun it.
        if checkpoint_state.get("max_date", ""):
            recalculated_date = datetime.datetime.utcnow() - datetime.timedelta(days=10)
            if dateutil.parser.parse(checkpoint_state["max_date"]) < recalculated_date:
                startDate = dateutil.parser.parse(
                    recalculated_date.strftime("%Y-%m-%dT%H:%M:%S")
                )
                self._ckpt.update(
                    self._name,
                    {
                        "state": json.dumps(
                            {"max_date": str(startDate), "nextlink": "", "page_no": 0}
                        )
                    },
                )
                logger.info(
                    "The Date retrived from checkpoint is more than 10 days in the past hence the data collection will start from following Start Date: %s"
                    % (startDate)
                )
                return startDate
            return dateutil.parser.parse(checkpoint_state["max_date"])
        else:
            # No check point date, so look if a start date was specified as an argument
            date = self._parameters.start_date_time
            if date:
                if dateutil.parser.parse(
                    date
                ) < datetime.datetime.now() - datetime.timedelta(days=10):
                    startDate = datetime.datetime.now() - datetime.timedelta(days=10)
                    logger.info(
                        "The Date Specified is more than 10 days in the past hence the data collection will start from following Start Date: %s"
                        % (startDate)
                    )
                    return startDate
                return dateutil.parser.parse(date)
            else:
                # If there was no start date specified, default to 5 days ago
                return datetime.datetime.now() - datetime.timedelta(days=5)

    """
    def _get_events_continuous
    Ingest the data for continuously_monitor input mode.
    The end_date will be calculated based upon specified start_date and query_window_size
    """

    def _get_events_continuous(self, app):
        messages = None
        query_window_size = int(self._parameters.query_window_size)
        delay_throttle = int(self._parameters.delay_throttle)
        checkpoint_key = self._name
        while True:
            if app.is_aborted():
                return

            else:
                start_date = self.get_start_date(checkpoint_key)
                end_date = start_date + datetime.timedelta(minutes=query_window_size)
                logger.info(
                    "Collecting the data between Start date: %s, End date: %s"
                    % (start_date, end_date)
                )
                utc_now = datetime.datetime.utcnow()

                if end_date > utc_now - datetime.timedelta(minutes=delay_throttle):
                    logger.info(
                        "End Date is greater than the specified delay throttle [start_date=%s end_date=%s utc_now=%s] Skipping..."
                        % (start_date, end_date, utc_now)
                    )
                    return

                self._process_messages(start_date, end_date, input_mode="cont_mon")
                max_date = str(end_date)

                if not self._ckpt.get(self._name):
                    self._ckpt.save(
                        {
                            "_key": checkpoint_key,
                            "state": json.dumps(
                                {
                                    "max_date": max_date,
                                    "nextlink": "",
                                    "page_no": 0,
                                    "query_window": query_window_size,
                                }
                            ),
                        }
                    )
                else:
                    self._ckpt.update(
                        checkpoint_key,
                        {
                            "state": json.dumps(
                                {
                                    "max_date": max_date,
                                    "nextlink": "",
                                    "page_no": 0,
                                    "query_window": query_window_size,
                                }
                            )
                        },
                    )
                logger.debug(
                    "Checkpoint is updated to max_date=%s for datainput=%s"
                    % (max_date, self._name)
                )

    """
    def get_session
    Returns session object after applying the headers on it.
    """

    def get_session(self):
        if self._token.need_retire(min_ttl=600):
            self._session = self._proxy.create_requests_session()
            session = self._token.auth(self._session)
        else:
            session = self._token.set_auth_header(self._session)

        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                allowed_methods=None,
                status_forcelist=STATUS_CODE_LIST,
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    """
    def _get_messages
    Get messages from reporting API between specified start_date and end_date
    """

    def _get_messages(self, url):
        try:
            session = self.get_session()
            session.headers.update(
                {"Content-type": "application/json", "Accept": "application/json"}
            )

            response = session.get(url, timeout=120)
            response.raise_for_status()
            response_json = None
            response_json = json.loads(response.content)
            messages = response_json

        except Exception as e:
            error_message = "HTTP Request error: %s" % str(e)
            logger.error(error_message, exc_info=True, stack_info=True)
            raise e
        return messages

    """
    def _skip_pages
    Skip page_number number of pages and return url retrived from last page
    """

    def _skip_pages(self, start_date, end_date, page_number):
        logger.info(
            "Nextlink is expired, Hence retriving nextlink by skipping the pages"
        )
        microsoft_trace_url = baseUrl + reportingUrl.format(
            start_date.isoformat(), end_date.isoformat()
        )
        message_response = self._get_messages(microsoft_trace_url)
        url = None
        for page in range(int(page_number)):
            if "@odata.nextLink" in message_response:
                url = message_response["@odata.nextLink"]
            elif "odata.nextLink" in message_response:
                url = message_response["odata.nextLink"]
            else:
                return None
            url = self._get_url(url)
            if page != page_number - 1:
                logger.info("Skipping data for nextlink: %s" % url)
            message_response = self._get_messages(url)

        return url

    """
    def _get_state_from_kv
    return nextlink, page_no and query_window from kvstore
    """

    def _get_state_from_kv(self):
        data = self._ckpt.get(self._name)
        if data:
            state = json.loads(data["state"])
            return (
                state.get("nextlink", ""),
                state.get("page_no", 0),
                state.get("query_window", None),
            )
        else:
            return "", 0, None

    """
    def _has_expired
    Check whether nexlink stored in the kvstore is expired
    """

    def _has_expired(self, url):
        try:
            session = self.get_session()
            session.headers.update(
                {"Content-type": "application/json", "Accept": "application/json"}
            )

            response = session.get(url, timeout=120)
            if response.status_code != 200:
                return True
            else:
                return False
        except Exception as e:
            return True

    """
    def _process_messages
    Process the messages received from reporting API
    """

    def _process_messages(self, start_date, end_date, input_mode):
        total_ingested_events = 0
        microsoft_trace_url = None
        nextlink, page_no, query_window_from_kv = self._get_state_from_kv()
        use_nextlink = True
        if input_mode == "cont_mon":
            query_window_from_conf = int(self._parameters.query_window_size)
            if (
                query_window_from_kv
                and query_window_from_kv != query_window_from_conf
                and nextlink
            ):
                logger.warning(
                    "Data collection of last window was not completed and Query Window Size is updated. This might lead to data duplication."
                )
                use_nextlink = False

        if nextlink and use_nextlink:
            if not self._has_expired(nextlink):
                microsoft_trace_url = nextlink
                logger.info(
                    "Nextlink found in checkpoint. Starting data collection from nextlink {}".format(
                        microsoft_trace_url
                    )
                )
            else:
                microsoft_trace_url = self._skip_pages(start_date, end_date, page_no)
                logger.info(
                    "Starting data collection from nextlink {}".format(
                        microsoft_trace_url
                    )
                )

        if not microsoft_trace_url:
            microsoft_trace_url = baseUrl + reportingUrl.format(
                start_date.isoformat(), end_date.isoformat()
            )

        message_response = self._get_messages(microsoft_trace_url)
        messages = message_response["value"] or None

        while messages:
            for message in messages:
                # According to https://learn.microsoft.com/en-us/previous-versions/office/developer/o365-enterprise-developers/jj984335(v=office.15)?redirectedfrom=MSDN#using-startdate-and-enddate
                # The StartDate and EndDate fields do not provide useful information in the report results...
                # Sometimes popping "StartDate" fails because of unknown issue. So to avoid an unexpected error, Try/Except method is used here.
                try:
                    message.pop("StartDate", None)
                    message.pop("EndDate", None)
                    self._event_writer.write_event(json.dumps(message))
                    total_ingested_events += 1
                except Exception as e:
                    logger.error(
                        "An error occurred while ingesting data",
                        exc_info=True,
                        stack_info=True,
                    )

            sys.stdout.flush()
            messages = None

            nextLink = None
            if "@odata.nextLink" in message_response:
                nextLink = message_response["@odata.nextLink"]

            if "odata.nextLink" in message_response:
                nextLink = message_response["odata.nextLink"]

            if nextLink is not None:
                nextLink = self._get_url(nextLink)
                logger.debug("nextLink URL (@odata.nextLink): %s" % nextLink)
                checkpoint_date = self._ckpt.get(self._name)
                if not checkpoint_date:
                    if input_mode == "index_once":
                        self._ckpt.save(
                            {
                                "_key": self._name,
                                "state": json.dumps(
                                    {"nextlink": nextLink, "page_no": 1}
                                ),
                            }
                        )
                    else:
                        self._ckpt.save(
                            {
                                "_key": self._name,
                                "state": json.dumps(
                                    {
                                        "nextlink": nextLink,
                                        "page_no": 1,
                                        "query_window": query_window_from_conf,
                                    }
                                ),
                            }
                        )
                else:
                    checkpoint_state = json.loads(checkpoint_date["state"])
                    if not use_nextlink:
                        checkpoint_state["page_no"] = 1
                        use_nextlink = True
                    else:
                        checkpoint_state["page_no"] = (
                            checkpoint_state.get("page_no", 0) + 1
                        )
                    checkpoint_state["nextlink"] = nextLink
                    if input_mode == "cont_mon":
                        checkpoint_state["query_window"] = query_window_from_conf
                    checkpoint_date["state"] = json.dumps(checkpoint_state)
                    self._ckpt.batch_save([checkpoint_date])

                # This should never happen, but just in case...
                if not self._is_https(nextLink):
                    raise ValueError(
                        "nextLink scheme is not HTTPS. nextLink URL: %s" % nextLink
                    )

                message_response = self._get_messages(nextLink)
                messages = message_response["value"] or None
        logger.info(
            "Total number of ingested messages are {}".format(total_ingested_events)
        )

    """
    def _get_events_once
    Ingest the data between specified start_date and end_date for index_once input mode
    """

    def _get_events_once(self):
        messages = None

        start_date = dateutil.parser.parse(self._parameters.start_date_time)
        end_date = dateutil.parser.parse(self._parameters.end_date_time)

        checkpoint_date = self._ckpt.get(self._name)

        if checkpoint_date:
            checkpoint_state = json.loads(checkpoint_date["state"])
            if checkpoint_state.get("start_date", ""):
                check_start_date = dateutil.parser.parse(checkpoint_state["start_date"])
                check_end_date = dateutil.parser.parse(checkpoint_state["end_date"])

                if (check_start_date == start_date) and (check_end_date == end_date):
                    logger.info(
                        'Skipped "input Name = %s " since events between %s and %s should have been indexed'
                        % (self._name, start_date, end_date)
                    )
                    return

        self._process_messages(start_date, end_date, input_mode="index_once")
        date1 = str(start_date)
        date2 = str(end_date)
        if not self._ckpt.get(self._name):
            self._ckpt.save(
                {
                    "_key": self._name,
                    "state": json.dumps(
                        {
                            "start_date": date1,
                            "end_date": date2,
                            "nextlink": "",
                            "page_no": 0,
                        }
                    ),
                }
            )
        else:
            self._ckpt.update(
                self._name,
                {
                    "state": json.dumps(
                        {
                            "start_date": date1,
                            "end_date": date2,
                            "nextlink": "",
                            "page_no": 0,
                        }
                    )
                },
            )
        logger.debug(
            "Checkpoint is updated to start_date=%s and end_date=%s for datainput=%s"
            % (date1, date2, self._name)
        )

    def run(self, app):
        if self._validate_input():
            try:
                self._collect_events(app)
            except Exception as e:
                logger.error(
                    "An error occurred while collecting data",
                    exc_info=True,
                    stack_info=True,
                )


"""
    class MessageTraceDataInput
    This class sets up the modular input including setting up authentication,
    proxy and other session information.

"""


class MessageTraceDataInput(object):
    def __init__(self, stanza):
        self._kind = stanza.kind
        self._name = stanza.name
        self._args = stanza.content
        self._start_time = int(time.time())

    def _create_metadata(self):
        stanza = self._kind + "://" + self._name
        parser = StanzaParser(
            [
                StringField("index"),
                StringField("host"),
                StringField("stanza", fillempty=stanza),
                StringField("sourcetype", default="o365:reporting:messagetrace"),
            ]
        )
        # often splunk will not resolve $decideOnStartup if not use the OS's
        # host name
        metadata = self._extract_arguments(parser)
        if metadata.host == "$decideOnStartup":
            metadata.host = platform.node()
        return metadata

    def _extract_arguments(self, parser):
        return parser.parse(self._args)

    def _get_tenant_name(self):
        parser = StanzaParser(
            [
                StringField("tenant_name"),
            ]
        )
        args = self._extract_arguments(parser)
        return args.tenant_name

    def _create_event_writer(self, app):
        metadata = self._create_metadata()
        return app.create_event_writer(None, **vars(metadata))

    def _create_tenant(self, config):
        tenant_name = self._get_tenant_name()
        return O365Tenant.create(config, tenant_name)

    def _create_consumer(self, event_writer, proxy, token, args, name, checkpoint):
        return MessageTraceConsumer(event_writer, proxy, token, args, name, checkpoint)

    @property
    def name(self):
        return self._name

    @property
    def start_time(self):
        return self._start_time

    @LogWith(datainput=name, start_time=start_time)
    @LogExceptions(
        logger, "Data input was interrupted by an unhandled exception.", lambda e: -1
    )
    def run(self, app, config):
        Logging.load(config).apply()
        proxy = Proxy.load(config)
        registry = O365PortalRegistry.load(config)
        tenant = self._create_tenant(config)
        messagetrace = tenant.create_messagetrace_portal(registry)
        policy = tenant.create_messagetrace_token_policy(registry)
        token = messagetrace.create_messagetrace_token_provider(policy)
        event_writer = self._create_event_writer(app)
        kv_collection_name = "splunk_ta_o365_messagetrace_checkpoint_collection"
        checkpoint = KVStoreCheckpoint(
            collection_name=kv_collection_name,
            service=config._service,
            fields={"state": "string"},
        )
        checkpoint.get_collection()
        consumer = self._create_consumer(
            event_writer, proxy, token, self._args, self._name, checkpoint
        )
        consumer.run(app)


"""
    def modular_input_run
    This will trigger calls to the Microsoft Reporting API to get data related to MessageTrace.
"""


def modular_input_run(app, config):
    array = app.inputs()
    data_input = MessageTraceDataInput(array[0])
    return data_input.run(app, config)


"""
    def main
    Accepts arguments for the tenant_name,input_mode,start_date_time,end_date_time,query_window_size and delay_throttle and runs SimpleCollectorV1 to ingest MessageTrace events from the Microsoft Reporting API.
"""


def main():
    arguments = {
        "tenant_name": {
            "title": "Tenant Name",
            "description": "Which Office 365 tenant will be used.",
        },
        "input_mode": {
            "title": "Input Mode",
            "description": 'Selecting "Index Once" ignores "Query window size" and "Delay throttle". Additionally, "Start date/time" and "End date/time" are required for "Index Once".',
        },
        "start_date_time": {
            "title": "Start date/time",
            "description": "Date/time to start collecting message traces. If no date/time is given, the input will start 5 days in the past.",
        },
        "end_date_time": {
            "title": "End date/time",
            "description": 'Only specify an end date/time if using the "Index Once" option.',
        },
        "query_window_size": {
            "title": "Query Window Size (minutes)",
            "description": "Specify how many minute's worth of data to query each interval. See https://splunkbase.splunk.com/app/4055/#/details for more information.",
        },
        "delay_throttle": {
            "title": "Delay Throttle (minutes)",
            "description": 'Microsoft may delay trace events up to 24 hours. Specify how close to "now" a query may run. See https://splunkbase.splunk.com/app/4055/#/details for more information.',
        },
    }

    SimpleCollectorV1.main(
        modular_input_run,
        title="Splunk Add-on for Microsoft Office 365 Message Trace",
        description="Ingest MessageTrace events from Office 365 Reporting API",
        use_single_instance=False,
        arguments=arguments,
    )

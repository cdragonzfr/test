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
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from datetime import datetime, timedelta
from splunk_ta_o365.common.portal import O365PortalError, O365PortalRegistry
from splunk_ta_o365.common.settings import Logging, Proxy
from splunk_ta_o365.common.tenant import O365Tenant
from splunk_ta_o365.common.utils import time_taken, time_to_string, string_to_time
from splunk_ta_o365.common.checkpoint import KVStoreCheckpoint
from splunk_ta_o365.common.checkpoint_migration import (
    CheckpointMigrationV2,
)

from splunksdc import logging
from splunksdc.batch import BatchExecutor
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import IntegerField, StanzaParser, StringField
from splunksdc.utils import LogExceptions, LogWith
from typing import List, Tuple, Union, Dict, TypeVar, Any


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.get_module_logger()
token_refresh_lock = threading.RLock()

# If no allowed_methods param passed the default will be
# DEFAULT_ALLOWED_METHODS = frozenset(
#         ["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"]
#     )
STATUS_CODE_LIST = [408, 429, 500]
ALLOWED_METHODS = None
wait_time_for_retry = 1
retry_count = 2

RETRY_LATER_STATUS_CODE = ("401", "500", "502", "ConnectionError")
RETRY_NOW_STATUS_CODE = ("ReadTimeout", "429", "ConnectTimeout")

MAX_ALLOWED_TIME = {
    "days": 6,
    "hours": 23,
}

Requests = TypeVar("Requests")


class DataInput(object):
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
                StringField("sourcetype", default="o365:management:activity"),
            ]
        )
        # often splunk will not resolve $decideOnStartup if not use the OS's
        # host name
        metadata = self._extract_arguments(parser)
        if metadata.host == "$decideOnStartup":
            metadata.host = platform.node()
        return metadata

    def _get_tenant_name(self):
        parser = StanzaParser(
            [
                StringField("tenant_name"),
            ]
        )
        args = self._extract_arguments(parser)
        return args.tenant_name

    def _get_start_date_time(self):
        parser = StanzaParser(
            [
                StringField("start_date_time"),
            ]
        )
        args = self._extract_arguments(parser)
        return self._get_valid_date(args.start_date_time)

    def _get_valid_date(self, timestamp: str) -> datetime:
        """
        Validate the given timestamp

        Args:
            timestamp (str): time to be validated

        Raises:
            e: Exception when parsing failed

        Returns:
            datetime: parsed datetime
        """
        if timestamp is not None:
            try:
                timestamp = dateutil.parser.parse(timestamp)
            except Exception as e:
                # (dateutil.parser.ParserError, TypeError)
                error_message = "Unable to parse specified Start Date/Time"
                logger.error(error_message, exc_info=True, stack_info=True)
                raise e
        return timestamp

    def _create_tenant(self, config):
        tenant_name = self._get_tenant_name()
        return O365Tenant.create(config, tenant_name)

    def _create_event_writer(self, app):
        metadata = self._create_metadata()
        return app.create_event_writer(None, **vars(metadata))

    def _create_subscription(self, mgmt):
        parser = StanzaParser(
            [
                StringField("content_type"),
                IntegerField("request_timeout", lower=10, upper=600, default=60),
            ]
        )
        args = self._extract_arguments(parser)
        return mgmt.create_subscription(args.content_type, args.request_timeout)

    def _create_executor(self):
        parser = StanzaParser(
            [
                IntegerField("number_of_threads", lower=4, upper=64, default=16),
            ]
        )
        args = self._extract_arguments(parser)
        return BatchExecutor(number_of_threads=args.number_of_threads)

    def _create_token_refresh_window(self):
        parser = StanzaParser(
            [
                IntegerField(
                    "token_refresh_window", lower=400, upper=3600, default=600
                ),
            ]
        )
        args = self._extract_arguments(parser)
        return args.token_refresh_window

    def _extract_arguments(self, parser):
        return parser.parse(self._args)

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
        mgmt = tenant.create_management_portal(registry)
        policy = tenant.create_v2_token_policy(registry)
        token = mgmt.create_token_provider(policy)
        subscription = self._create_subscription(mgmt)
        event_writer = self._create_event_writer(app)
        executor = self._create_executor()
        token_refresh_window = self._create_token_refresh_window()
        start_date_time = self._get_start_date_time()

        adapter = Adapter(
            app,
            proxy,
            token,
            subscription,
            event_writer,
            token_refresh_window,
            self.name,
            self._kind,
            config,
            start_date_time,
        )
        executor.run(adapter)
        return 0


class Adapter(object):
    def __init__(
        self,
        app,
        proxy,
        token,
        subscription,
        event_writer,
        token_refresh_window,
        input_name,
        kind,
        config,
        start_date_time,
    ):
        self._app = app
        self._proxy = proxy
        self._token = token
        self._subscription = subscription
        self._event_writer = event_writer
        self._kind = kind
        self._config = config
        self._token_refresh_window: int = token_refresh_window
        self._input_name: str = input_name
        self._time_format = "%Y-%m-%dT%H:%M:%S"
        self._start_date_time: datetime = start_date_time

        self._session: Requests = None

        self._is_migrated: bool = False
        self._is_migration_required: bool = False

        self._now: datetime = time.time

        self._is_listing_content: bool = False
        self._retry_now: List[Dict] = None
        self._retry_later: bool = None

        self.checkpoint_info_temp: dict = None
        self._ingested_contents: list = None

        self._migrate_checkpoint: CheckpointMigrationV2 = None
        self._checkpoint: KVStoreCheckpoint = None
        self._load_checkpoint()

    def is_aborted(self) -> bool:
        """
        Check if aborted

        Returns:
            bool: aborted or not
        """
        return self._app.is_aborted()

    def _load_checkpoint(self) -> None:
        """
        Load | create collection for checkpointing
        """
        self._checkpoint = KVStoreCheckpoint(
            collection_name=self._kind, service=self._config._service
        )
        self._checkpoint.get_collection()

    def _update_token(self, session: Requests) -> None:
        """
        Update token if it's retired or about to.

        Args:
            session (Requests): requests session object
        """
        if self._token.need_retire(self._token_refresh_window):
            logger.info("Access token will expire soon.")
            self._token.auth(session)

    def _handle_token_expiration(self, session: Requests) -> None:
        """
        Handle token update for multiple threads, making sure only
        one thread update the token.

        Args:
            session (Requests): requests session object
        """
        if self._token.need_retire(self._token_refresh_window):
            with token_refresh_lock:
                # we will again check need_retire() condition to avoid multiple-thread
                # waiting to gain access not update the token again.
                self._update_token(session)

    def _time_to_string(self, timestamp: datetime) -> str:
        """
        Convert the datetime obj to string

        Args:
            timestamp (datetime): time to be converted

        Returns:
            str: converted timestamp
        """
        return time_to_string(self._time_format, timestamp)

    def _string_to_time(self, timestamp: str) -> datetime:
        """
        Convert the string obj to datetime

        Args:
            timestamp (str): time to be converted

        Returns:
            datetime: converted timestamp
        """
        return string_to_time(self._time_format, timestamp)

    def _normalize_time_range(
        self, start_time: datetime, end_time: datetime
    ) -> Tuple[datetime, datetime]:
        """
        Yield tuples of start and end times that represent hourly intervals within the
        given time range.

        Args:
            start_time (datetime): The start time of the time range.
            end_time (datetime): The end time of the time range.

        Yields:
            Tuple[datetime, datetime]: A tuple containing the start and end times of an
            hourly interval within the time range.
        """
        delta = timedelta(hours=1)
        while end_time - start_time > delta:
            _end_time = start_time + delta
            yield start_time, _end_time
            start_time = _end_time
        yield start_time, end_time

    def _get_relative_time(self, **kwargs) -> Tuple[datetime, datetime]:
        """
        Args:
            days/hours/mins...
            example: days=7,hours=4
                    _get_relative_time(days=4, hours=3)
                    _get_relative_time(days=4)

        Returns:
            Tuple[datetime, datetime]: relative time and current time
        """
        now = datetime.utcfromtimestamp(self._now())
        return now - timedelta(**kwargs), now

    def _get_session(self) -> Requests:
        """
        Get session and authenticate token

        Returns:
            Requests: requests session object
        """
        session = self._proxy.create_requests_session()
        self._token.auth(session)
        self._enable_subscription(session)
        return session

    def _enable_subscription(self, session: Requests) -> None:
        """
        Enable subcription

        Args:
            session (Requests): requests session object
        """
        if not self._subscription.is_enabled(session):
            self._subscription.start(session)

    def _fetch_update_migration_status(self, checkpoint_info: dict) -> None:
        """
        Fetch migration code from object and update it

        Args:
            checkpoint_info (dict): checkpoint dict.
        """
        _is_migrated = checkpoint_info.get("is_migrated", False)
        self._set_migration_status(_is_migrated)

    def _validate_start_time(
        self, _start_time: datetime
    ) -> Tuple[bool, datetime, datetime]:
        """
        Validate the given start time

        Args:
            _start_time (datetime): start time value

        Returns:
            Tuple[bool, datetime, datetime]: multiple data
        """
        _is_valid = True
        max_start_time_allowed, _end_time = self._get_relative_time(**MAX_ALLOWED_TIME)
        if max_start_time_allowed > _start_time:
            if not self._check_valid_time(_start_time):
                _is_valid = False
                self._warn_user_invalid_start_time(max_start_time_allowed)
                _start_time = max_start_time_allowed

        return _is_valid, _start_time, _end_time

    def _get_temp_checkpoint_details(
        self, prev_checkpoint_temp: dict
    ) -> Union[datetime, datetime, List[str]]:
        """
        Get details for temp checkpoint

        Args:
            prev_checkpoint_temp (dict): prev checkpoint temp

        Returns:
            Union[datetime, datetime, List[str]]: start, end, contents

        Notes:
            if _start_time of temp info is beyond 7 days - make API call to validate
            the time, then resetting it back to 6days and 23hrs timestamp and
            _end_time will be now()
        """
        _s_time = prev_checkpoint_temp.get("start_time")
        _start_time = self._string_to_time(_s_time)
        _end_time = self._string_to_time(prev_checkpoint_temp.get("end_time"))
        self._fetch_update_migration_status(prev_checkpoint_temp)

        logger.info("Fetching details for skipped contents", start_time=_s_time)
        contents_stored = prev_checkpoint_temp.get("contents", [])
        _is_valid, _start_time, _end_time_allowed = self._validate_start_time(
            _start_time
        )
        if not _is_valid:
            _end_time = _end_time_allowed

        return _start_time, _end_time, contents_stored

    def _get_checkpoint_details(
        self, prev_checkpoint: dict
    ) -> Union[datetime, datetime]:
        """
        Get checkpoint details

        Args:
            prev_checkpoint (dict): prev checkpoint

        Returns:
            Union[datetime, datetime]: start, end, contents

        Notes:
            last stored end_time will now be start_time for next input invocation
            start_time should not be older than 7 days
            if do then overwrite the start_time with 6 days and 23 hrs older timestamp
        """
        _start_time = self._string_to_time(prev_checkpoint.get("end_time"))
        self._fetch_update_migration_status(prev_checkpoint)
        _, _start_time, _end_time = self._validate_start_time(_start_time)
        return _start_time, _end_time

    def _get_init_time(self, _start_time: datetime) -> Tuple[datetime, datetime]:
        """
        Get the timerage for first input invocation

        Args:
            _start_time (datetime): start time for query

        Returns:
            Tuple[datetime, datetime]: validated start and end time

        Notes:
            keeping is_migrated False if first time input invoked
        """
        self._set_migration_status(False)
        if not _start_time:
            _start_time, _end_time = self._get_relative_time(hours=4)
        else:
            _, _start_time, _end_time = self._validate_start_time(_start_time)

        return _start_time, _end_time

    def _warn_user_invalid_start_time(self, default_start_time: datetime) -> None:
        """
        Add log for warning for invalid time

        Args:
            default_start_time (datetime): Default start time
        """
        logger.warn(
            f"Resetting start time to: {self._time_to_string(default_start_time)}"
        )

    def _get_timerange(
        self, prev_checkpoint: dict, prev_checkpoint_temp: dict
    ) -> Union[datetime, datetime, List[Dict]]:
        """
        Gets the time range for ingesting contents based on checkpoint information.

        Args:
            prev_checkpoint (dict): Checkpoint information dictionary for
                main checkpoint.
            prev_checkpoint_temp (dict): Checkpoint information dictionary for
                temp checkpoint.

        Returns:
            Union[datetime, datetime, List[Dict]]: Returns a tuple of start_time and
                end_time datetime objects and a list of contents already stored
                in temp checkpoint.
        """
        contents_stored = []

        if prev_checkpoint_temp:
            _start_time, _end_time, contents_stored = self._get_temp_checkpoint_details(
                prev_checkpoint_temp
            )
        elif prev_checkpoint:
            _start_time, _end_time = self._get_checkpoint_details(prev_checkpoint)
        else:
            _start_time, _end_time = self._get_init_time(self._start_date_time)

        return _start_time, _end_time, contents_stored

    def _check_valid_time(self, start_time: datetime) -> bool:
        """
        Check if given start_time is valid

        Args:
            start_time (datetime): start time

        Returns:
            bool: if start time valid
        """
        end_time = start_time + timedelta(minutes=5)
        return self._test_api_response(start_time, end_time)

    def _test_api_response(self, start_time: datetime, end_time: datetime) -> bool:
        """
        Make API call with given time ranges

        Args:
            start_time (datetime): start time
            end_time (datetime): end time

        Raises:
            e: API error

        Returns:
            bool: Valid or not
        """
        try:
            self._subscription.list_available_content(
                self._session, start_time, end_time
            )
            return True
        except Exception as e:
            if isinstance(e, O365PortalError):
                if e.is_time_range_error():
                    logger.warn(e.get_error_message())
                    return False
            raise e

    def _load_migration(self) -> None:
        """
        Load migration checkpoint for current ingestion process and check if
        validation is required.

        Loads the CheckpointMigrationV2 instance and
        checks if validation of the checkpoint is required by calling
        load_checkpoint() method.

        Args:
            None

        Returns:
            None
        """
        _is_migrated = self._get_migration_status()
        if not _is_migrated:
            self._is_migration_required = True
            self._migrate_checkpoint = CheckpointMigrationV2(
                self._app,
                self._config,
                self._kind,
                self._input_name,
            )
            if not self._migrate_checkpoint.load_checkpoint():
                self._is_migration_required = False
            logger.debug(
                "Validation(checkpoint) required during ingestion",
                value=self._is_migration_required,
            )

    def _set_migration_status(self, value: bool) -> None:
        """
        Set the migration status

        Args:
            value (bool): value to be set
        """
        self._is_migrated = value

    def _get_migration_status(self) -> bool:
        """
        Get the migration status

        Returns:
            bool: value of migration status
        """
        return self._is_migrated

    def _make_temp_info(self, start_time: datetime, end_time: datetime) -> None:
        """
        Create temporary ingestion info for the current ingestion session with
        the given start and end times.

        Args:
            start_time (datetime): Start time of the ingestion session.
            end_time (datetime): End time of the ingestion session.

        Returns:
            None
        """
        _is_migrated = self._get_migration_status()
        self._ingested_contents = []
        self.checkpoint_info_temp.update(
            start_time=self._time_to_string(start_time),
            end_time=self._time_to_string(end_time),
            contents=self._ingested_contents,
            is_migrated=_is_migrated,
        )

    def _filter_ingested_contents(
        self, contents: List[Dict], contents_stored: List[str]
    ) -> List[Dict]:
        """
        Filter the given contents to remove the ones that have already been ingested.
        This method validates the contents from an older checkpoint if migration is
        required, and from temporary checkpoint information if there was an
        exception in the last iteration.

        Args:
            contents (List[Dict]): A list of dictionaries representing the contents
                to filter.
            contents_stored (List[str]): A list of strings representing the IDs
                of the contents that have already been ingested.

        Returns:
            List[Dict]: A list of dictionaries representing the filtered contents.
        """
        if self._is_migration_required:
            # filter out already ingested contents from older checkpoint
            contents = [
                content
                for content in contents
                if not self._has_ingested(content["contentId"])
            ]
        elif contents_stored:
            # filter out already ingested contents from temp-checkpoint
            contents = [
                content
                for content in contents
                if content["contentId"] not in contents_stored
            ]
        return contents

    def discover(self):
        """
        The discover method is a generator that yields all the jobs/tasks to fetch.

        Yields:
            list: A list of available contents to ingest.

        Raises:
            Exception: If there is any error while retrieving content,
            it will raise an exception.

        Notes:
            This method uses a temporary checkpoint to store information
            in case of any exceptions or failures during API calls,
            ingestion, or input-disabled.
            It also uses a main checkpoint to keep track of the last ingested
            events time to continue the next cycle beyond that timestamp.
            The `_post_ingestion_task` method is called after processing
            all contents to clear the temporary checkpoint information,
            update the migration flag, and delete the older checkpoint
            if the `_is_migration_required` is set to true.
            The `_handle_retry_now` method is called to retry any failed tasks.
            The `list_available_content` method is called to fetch the contents
            for a given time range.
        """
        session = self._get_session()
        self._session = session

        checkpoint_key = self._checkpoint.get_valid_name(
            f"{self._input_name}_{self._subscription.get_content_type()}"
        )
        temp_checkpoint_key = f"{checkpoint_key}_temp"

        prev_checkpoint = self._get_checkpoint_info(checkpoint_key)
        logger.debug(f"Checkpoint details: {prev_checkpoint}")
        prev_checkpoint_temp = self._get_checkpoint_info(temp_checkpoint_key)

        self._retry_now: List[Dict] = []
        self._retry_later: bool = False
        _start_time, _end_time, contents_stored = self._get_timerange(
            prev_checkpoint, prev_checkpoint_temp
        )
        _is_migrated = self._get_migration_status()
        self.checkpoint_info_temp = dict(_key=temp_checkpoint_key)
        checkpoint_info = dict(
            _key=checkpoint_key,
            is_migrated=_is_migrated,
        )

        # Check if migration needs to be done and load the checkpoint
        self._load_migration()

        # loop through time ranges (1 hr each)
        for start_time, end_time in self._normalize_time_range(_start_time, _end_time):
            try:
                _stringified_start_time = self._time_to_string(start_time)
                _stringified_end_time = self._time_to_string(end_time)
                logger.info(
                    "Start listing available content.",
                    start_time=_stringified_start_time,
                    end_time=_stringified_end_time,
                )
                # bring all the contents for given time range
                contents = self._subscription.list_available_content(
                    session, start_time, end_time
                )
                self._make_temp_info(start_time, end_time)
                contents = self._filter_ingested_contents(contents, contents_stored)
                if not contents:
                    logger.debug("All content in this page have been ingested.")
                    # update info here to avoid repetition of same timerange query again
                    self._update_checkpoint(
                        checkpoint_info, "end_time", _stringified_end_time
                    )
                    # updating the token to make sure in every scenario token refresh should happen
                    # even if it runs for an hour without getting any new contents.
                    self._update_token(session)
                    continue

                logger.info("Fresh content found.", size=len(contents))
                self._is_listing_content = True

                yield contents
                if self._retry_later:
                    # save the current state in temp checkpoint
                    logger.debug("Saving the current state in temp checkpoint.")
                    self._save_checkpoint_info([self.checkpoint_info_temp])
                    break

                # update token in session after processing all contents of the page
                # to avoid failure of next API call, if token already expired
                self._token.set_auth_header(session)
                self._update_token(session)
                self._update_checkpoint(
                    checkpoint_info, "end_time", _stringified_end_time
                )
            except Exception:
                logger.error(
                    'Failed to retrieve "list_available_content"',
                    exc_info=True,
                    stack_info=True,
                )
        yield self._handle_retry_now()
        self._post_ingestion_task(
            temp_checkpoint_key, prev_checkpoint_temp, checkpoint_info
        )

    def _handle_retry_now(self) -> List[Dict]:
        """
        Handle retry mechanism for failed contents

        Returns:
            List[Dict]: list of failed contents
        """
        # increasing the retry wait time and count for final retry call
        global wait_time_for_retry, retry_count
        wait_time_for_retry = 2
        retry_count = 3
        self._is_listing_content = False
        logger.debug(
            "Retrying failed contents blob",
            size=len(self._retry_now),
        )
        return self._retry_now

    def _post_ingestion_task(
        self,
        temp_checkpoint_key: str,
        prev_checkpoint_temp: dict,
        checkpoint_info: dict,
    ) -> None:
        """
        Perform post ingestion task
        -   clear temp checkpoint info
        -   delete migration checkpoint data
        -   update migration flag

        Args:
            temp_checkpoint_key (str): The temporary checkpoint key
                used during ingestion.
            prev_checkpoint_temp (dict): The ingestion info dictionary
                for the temporary checkpoint key.
            checkpoint_info (dict): Main checkpoint info

        Returns:
            None
        """
        self._clear_checkpoint_info(temp_checkpoint_key, prev_checkpoint_temp)
        if self._is_migration_required:
            self._close_conn()
            self._delete_old_checkpoint()
        self._update_migration_flag(checkpoint_info)

    def do(self, content: dict, session: Requests) -> list:
        """
        The do method retrieves the content from the given
        contentUri using the provided session, and returns
        a list of events retrieved from the blob.
        In case of any exception, it logs the error and
        returns the exception object.

        Args:
            content (dict): A dictionary containing information about the content.
            session (Requests): A requests.Session object to use for the request.

        Returns:
            list: A list of events extracted from the content blob.

        Raises:
            Exception: If the content blob retrieval fails,
            the exception is returned as it is.
        """
        try:
            self._handle_token_expiration(session)
            session = self._token.set_auth_header(session)
            response = self._subscription.retrieve_content_blob(
                session, content["contentUri"]
            )
            events = response.json()
            logger.debug(
                "Fetching events success.",
                content=content["contentId"],
                events=len(events),
            )
            return events
        except Exception as e:
            exc_info = False if isinstance(e, O365PortalError) else True
            if not self._is_listing_content:
                logger.error(
                    "Failed to retrieve content blob.",
                    content_id=content["contentId"],
                    exc_info=exc_info,
                )
            return e

    def done(self, content: dict, result: Union[List[Dict], Exception]) -> None:
        """
        Process the result of a content retrieval operation, and take appropriate
        action based on the outcome.

        Args:
            content (dict): A dictionary containing information about the content
                that was retrieved.
            result (Union[List[Dict], Exception]): The result of the retrieval
                operation. This can be a list of dictionaries representing the content
                items retrieved, or an exception object indicating that the retrieval
                operation failed.

        Returns:
            None

        Raises:
            None
        """
        if not isinstance(result, Exception):
            self._ingest_content_blob(content, result)
        else:
            error_type = type(result).__name__
            status_code = (
                result.get_status_code()
                if isinstance(result, O365PortalError)
                else None
            )
            if (status_code or error_type) in RETRY_LATER_STATUS_CODE:
                self._retry_later = True
            elif (status_code or error_type) in RETRY_NOW_STATUS_CODE:
                self._retry_now.append(content)
            else:
                logger.debug(
                    "Unknown status code or error type.",
                    error_type=error_type,
                    status_code=status_code,
                    content_id=content["contentId"],
                )

    def allocate(self):
        """
        Session will be allocated to each thread of do() method
        to avoid any connection-pool failure or any
        discrepancy with threading

        Allocate a new HTTP session and configure retry policies
        for handling network errors.

        Returns:
        A new instance of requests.Session with the retry policies configured.

        Example:
        allocator = SessionAllocator(proxy)
        session = allocator.allocate()
        response = session.get('https://example.com')
        """
        session = self._proxy.create_requests_session()
        # Handling retry in case request got timeout/too_many_requests/server error
        # to minimise any chance of data loss.
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=retry_count,
                backoff_factor=wait_time_for_retry,
                allowed_methods=ALLOWED_METHODS,
                status_forcelist=STATUS_CODE_LIST,
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _update_checkpoint(self, checkpoint_info: dict, key: str, value: Any) -> None:
        """
        update the info to the checkpoint

        Args:
            checkpoint_info (dict): checkpoint info
            time (datetime): timestamp
        """
        checkpoint_info[key] = value
        logger.debug(f"Checkpoint details: {checkpoint_info}")
        self._save_checkpoint_info([checkpoint_info])

    def _get_checkpoint_info(self, key: str) -> dict:
        """
        Get the info for the given key

        Args:
            key (str): unique key

        Returns:
            dict: checkpoint details
        """
        return self._checkpoint.get(key)

    def _save_checkpoint_info(self, data: List[Dict]) -> None:
        """
        Batch save checkpoint information for the given list of dictionaries.
        The function uses "batch_save" to insert or update the existing checkpoint.

        Args:
            data (List[Dict]): A list of dictionaries containing checkpoint information.

        Returns:
            None
        """
        self._checkpoint.batch_save(data)

    def _close_conn(self) -> None:
        """
        Close the connection if file is open
        """
        self._migrate_checkpoint.close()

    def _update_migration_flag(self, checkpoint_info: dict) -> None:
        """
        Updates the migration flag associated with the given key to the specified value.

        Args:
            checkpoint_info (dict): Checkpoint info

        Returns:
            None.

        Raises:
            None.

        This method checks if the `_is_migrated` is False,
        and if so, it update the checkpoint with True.
        """
        _is_migrated = self._get_migration_status()
        if not _is_migrated:
            logger.info("Updating migration flag to: True")
            self._update_checkpoint(checkpoint_info, "is_migrated", True)

    def _has_ingested(self, key: str) -> bool:
        """
        Check if given ID is already ingested in Splunk (from checkpoint info)

        Args:
            key (str): ID to check for

        Returns:
            bool: True if the ID is already ingested, False otherwise
        """
        if not self._migrate_checkpoint.get(key):
            return False
        return True

    def _delete_old_checkpoint(self) -> None:
        """
        delete the older checkpoint info
           - kvstore collection
           - FileBased collection
        """
        self._migrate_checkpoint.delete()

    @time_taken(logger, "Time consumed for ingesting events")
    def _ingest_content_blob(self, content: dict, events: List[Dict]) -> None:
        """
        Ingest given events into splunk
        Check if migration required:
            Ingest based on older mechanism
                to avoid duplication

        Ingest a blob of content along with a list of events.

        Args:
            content (dict): A dictionary representing the content to be ingested,
                containing at least a "contentUri" and a "contentId" key.
            events (List[Dict]): A list of dictionaries representing the events
                associated with the content.

        Returns:
            None.

        Raises:
            Exception: If an error occurs while ingesting the events.

        Notes:
            This method writes the events to a destination using the `_event_writer`
            object. If `_is_migrated` is set to `False`, it only writes events that have
            not been previously ingested, based on their "Id" attribute.

            Otherwise, it writes all events. Once ingestion is complete, the method
            appends the content's "contentId" to the `_ingested_contents` list.
            If an error occurs during ingestion, the method logs an error message and
            saves the content's ingestion info to a temp checkpoint, if `_is_listing_content`
            is `True`, before re-raising the exception.
        """
        total_ingested_events = len(events)
        content_id = content["contentId"]
        content_uri = content["contentUri"]
        try:
            if self._is_migration_required:
                for event in events:
                    event_id = event["Id"]
                    if not self._has_ingested(event_id):
                        self._event_writer.write_event(
                            json.dumps(event), source=content_uri
                        )
                    else:
                        logger.info(
                            "Events already exists with the same ID.", id=event_id
                        )
            else:
                for event in events:
                    self._event_writer.write_event(
                        json.dumps(event), source=content_uri
                    )
                # updating ingested contents list once ingestion completed.
                self._ingested_contents.append(content_id)
            logger.info(
                "Ingesting content success.",
                content_id=content_id,
                count=total_ingested_events,
            )
        except Exception as e:
            # In case of broken pipe error, checkpoint won't be updated,
            # on next cycle there will be a possibility of duplicate events
            # getting ingested.
            logger.info(
                "Exception occured while ingesting events",
                exception=str(e),
                events_count=total_ingested_events,
                content_id=content_id,
            )
            # save ingested contents info to recall the API with
            # same time-range to avoid duplication and data loss
            # for contents which got left behind
            if self._is_listing_content:
                logger.debug("Saving the current state in temp checkpoint.")
                self._save_checkpoint_info([self.checkpoint_info_temp])
            raise

    def _clear_checkpoint_info(self, id: str, checkpoint_info: dict) -> None:
        """
        Deletes the checkpoint info from collection

        Args:
            id (str): key or id to delete
            checkpoint_info (dict): checkpoint info
        """
        if checkpoint_info:
            self._checkpoint.delete_by_id(id)


def modular_input_run(app, config):
    array = app.inputs()
    di = DataInput(array[0])
    return di.run(app, config)


def main():
    arguments = {
        "tenant_name": {
            "title": "Tenant Name",
            "description": "Which Office 365 tenant will be used.",
        },
        "content_type": {
            "title": "Content Type",
            "description": "What kind of Management Activity will be ingested.",
        },
        "start_date_time": {
            "title": "Start date/time",
            "description": "Date/time to start collecting audit logs. If no date/time is given, the input will start 4 hours in the past.",
        },
        "number_of_threads": {
            "title": "Number of Threads",
            "description": "The number of threads used to download content blob in parallel.",
            "required_on_edit": False,
            "required_on_create": False,
        },
        "token_refresh_window": {
            "title": "Token Refresh Window",
            "description": "The number of seconds before the token's expiration time when the "
            "token should be refreshed.",
            "required_on_edit": False,
            "required_on_create": False,
        },
        "request_timeout": {
            "title": "Request Timeout",
            "description": "The number of seconds to wait before timeout while getting response from "
            "the subscription api.",
            "required_on_edit": False,
            "required_on_create": False,
        },
        "is_migrated": {
            "title": "Checkpoint migration flag",
            "description": "Indicate whether checkpoint has been migrated or not",
            "required_on_edit": False,
            "required_on_create": False,
        },
    }

    SimpleCollectorV1.main(
        modular_input_run,
        title="Splunk Add-on for Microsoft Office 365 Management Activity",
        description="Ingest audit events from Office 365 Management Activity API",
        use_single_instance=False,
        arguments=arguments,
    )

#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import time
import os
import json
from datetime import datetime, timedelta
from splunksdc import logging
from .endpoints import get_endpoint, NON_REPORT_CONTENT_TYPES
from splunk_ta_o365.common.checkpoint import KVStoreCheckpoint, FileBasedCheckpoint

import re
import urllib.parse


logger = logging.get_module_logger()


"""
    class GraphApiConsumer
    This class is used to make calls to the Microsoft Graph API to retrieve reports and then ingest the events using an eventwriter to splunk.
"""


class GraphApiConsumer(object):
    def __init__(self, name, app, config, event_writer, portal, proxy, token):
        """
        Manages retrieving and ingesting graph api data based on the endpoint

        Args:
            name (str): input name
            app (SimpleCollectorV1): Object of splunksdc.collector.SimpleCollectorV1
            config (ConfigManager): Object of splunksdc.config.ConfigManager
            event_writer (XMLEventWriter|HECWriter): event_writer to ingest the event in the splunk.
            portal (MSGraphPortalCommunications): This is an class that make api calls
            proxy (Proxy): A proxy with session for making REST calls
            token (O365TokenProvider): A token with credentials for validating the session
        """
        self._app = app
        self._name = name
        self._proxy = proxy
        self._token = token
        self._portal = portal
        self._service = config._service
        self._event_writer = event_writer
        self._now = time.time

    def get_checkpoint_collection(self, name: str):
        """
        This method used to create and load the KVstore collection

        Args:
            name (str): KVstore collection name
        """
        self._collection = KVStoreCheckpoint(name, self._service)
        self._collection.get_collection()

    def load_filebased_checkpoint(self):
        """
        This method used to load the legacy file-based checkpoint if checkpoint file exists.
        This method only used by the Audit and ServiceAnnouncement Input.
        """
        checkpoint_file: str = os.path.join(
            self._app._context.checkpoint_dir, self._name + ".ckpt"
        )
        if os.path.exists(checkpoint_file):
            self._legacy_checkpoint = FileBasedCheckpoint(checkpoint_file)
            self._legacy_checkpoint.load_checkpoint()
        else:
            self._ckpt["is_migrated"] = True

    def delete_legacy_report_checkpoint(self):
        """
        This method used to delete the legacy checkpoint file for Graph report endpoints inputs.
        """
        try:
            checkpoint_file: str = os.path.join(
                self._app._context.checkpoint_dir, self._name + ".ckpt"
            )
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                logger.info(
                    "Successfully removed stale checkpoint file.",
                    input_name=self._name,
                )
        except Exception as ex:
            logger.warn(
                "Exception occured while removing the file.", input_name=self._name
            )

    def get_query_window(
        self, checkpoint, look_back_days, ts_format="%Y-%m-%dT%H:%M:%SZ"
    ):
        """
        This method used to update the query parameter for Audit and ServiceAnnouncement input.

        Args:
            checkpoint (dict): Contains the checkpoint related information
            look_back_days (int): default look back time to consider for query start time
            ts_format (str, optional): timestamp format. Defaults to "%Y-%m-%dT%H:%M:%SZ".

        Returns:
            Returns the query window start and end time for API call.
        """
        qs_time = checkpoint["last_event_timestamp"]
        qe_time = datetime.utcnow()

        if str(qs_time).find(".") != -1:
            ts_format = "%Y-%m-%dT%H:%M:%S.%fZ"

        if not qs_time:
            qs_time = (qe_time - timedelta(days=look_back_days)).strftime(ts_format)
            checkpoint["last_event_timestamp"] = qs_time
        # For the audit logs input, will add one second in the last event timestamps
        elif checkpoint["event_count_offset"] == 0 and look_back_days == 1:
            qs_time = datetime.strptime(qs_time, ts_format)
            qs_time += timedelta(seconds=1)
            qs_time = qs_time.strftime(ts_format)

        qe_time = qe_time.strftime(ts_format)
        return qs_time, qe_time

    def update_session(self):
        """
        This method used to check if the token expired or it's about to expire
        """
        if self._token.need_retire(600):
            logger.info("Access token will expire soon.")
            self._token.auth(self._session)

    def ingest(self, event):
        """
        This used to ingest the events into the splunk

        Args:
            event (dict): unique event
        """
        self._event_writer.write_event(
            json.dumps(event),
            source=self._endpoint["source"],
            sourcetype=self._endpoint["sourcetype"],
        )

    def get_audit_service_data(self, next_link):
        """
        This method used to communicate with portal and retreive the data
        for AduitLogs and ServiceAnnouncement Input.

        Returns:
            Return the response value and nextLink from the API response
        """
        self.update_session()
        reports = self._portal.o365_graph_api(
            params=self._endpoint["params"],
            content_parser=self._endpoint["content_parser"],
            path=self._endpoint["path"],
        )
        items, next_link = reports.throttled_get(self._session, next_link)
        return items, next_link

    def ingest_audit_service_data(self, items):
        """
        This method used to ingest the data of the Audit and ServiceAnnouncement inputs.

        Args:
            items (list[dict]): response data of the API

        Raises:
            ex: Raise the exception to parent method if any.
        """
        try:
            ingested_events_count = skipped_count = 0
            event_count_offset = self._ckpt["event_count_offset"]

            for event in items:
                if not self._ckpt["is_migrated"] and self._legacy_checkpoint.get(
                    self._endpoint.get("message_factory")(event)
                ):
                    event_timestamp = event[self._endpoint["query_field"]]
                    logger.debug(f"Skipping the existing event : {event['id']}")
                    skipped_count += 1
                elif event_count_offset > 0:
                    logger.debug(f"Skipping the existing event : {event['id']}")
                    event_count_offset -= 1
                    skipped_count += 1
                else:
                    self.ingest(event)
                    event_timestamp = event[self._endpoint["query_field"]]
                    ingested_events_count += 1
                    self._ckpt["event_count_offset"] += 1

            if len(items) != 0:
                self._ckpt["event_count_offset"] = 0
                self._ckpt["last_event_timestamp"] = event_timestamp

            logger.info(
                "Total events summary.",
                received_events_count=len(items),
                skipped_count=skipped_count,
                ingested_events_count=ingested_events_count,
            )
        except Exception as ex:
            logger.info(
                "Exception occurred while ingesting the data. Total events summary.",
                received_events_count=len(items),
                skipped_count=skipped_count,
                ingested_events_count=ingested_events_count,
            )
            raise ex

    def audit_service_data_collector(self):
        """
        This method is used to collect the data of AuditLogs and serviceAnnouncement input

        Raises:
            ex: if there is any exception then raise it to parent method.
        """
        try:
            # Load File-based Checkpoint if migration is not completed
            if not self._ckpt["is_migrated"]:
                self.load_filebased_checkpoint()

            # Add page number field for exsting inputs transition
            if self._ckpt.get("page_number") is None:
                self._ckpt["nextLink"] = str()
                self._ckpt["page_number"] = -1

            # Update the filter Query if nextlink not present in the checkpoint and collect the data
            if not self._ckpt["nextLink"]:
                qs_time, qe_time = self.get_query_window(
                    self._ckpt, self._endpoint["look_back"]
                )
                self._endpoint["params"]["$filter"] = self._endpoint["params"][
                    "$filter"
                ].format(qs_time, qe_time)

            # Page number indicates which page is currently being processed
            current_page_number = (
                self._ckpt["page_number"] - 1 if self._ckpt["nextLink"] else -1
            )

            # Process pages flag indicates whether to process pages or skip the already ingested pages
            process_pages = True

            # Fetch nextLink from checkpoint
            next_link = self._ckpt["nextLink"]

            while True:
                try:
                    self._items, next_link = self.get_audit_service_data(next_link)
                except Exception as ex:
                    if hasattr(ex, "_status_code") and ex._status_code == "400":
                        logger.warning(
                            f"Encountered error, regenerating query window. StatusCode={ex._status_code}, ErrorCode={ex._code}, ErrorMessage={ex._err_message}"
                        )

                        # Extract start time and end time from nextLink containing invalid skiptoken
                        decoded_next_link = urllib.parse.unquote(next_link)
                        qs_time, qe_time = (
                            re.findall(
                                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                                decoded_next_link,
                            )
                        )[0:2]

                        # Update query parameters with same time window
                        self._endpoint["params"]["$filter"] = self._endpoint["params"][
                            "$filter"
                        ].format(qs_time, qe_time)

                        # Update process pages flag to skip pages
                        # Set current page number to -1 as we start fresh query window
                        # Discard nextLink
                        process_pages, current_page_number, next_link = False, -1, None

                        # Skip following steps and start fresh invocation
                        continue
                    else:
                        raise ex

                # Increase the page number count to indicate the new page being processed
                current_page_number += 1

                # Check if need to skip pages or process pages - If not process pages, then skip already ingested pages
                if not process_pages:
                    if current_page_number < int(self._ckpt["page_number"]):
                        logger.debug(
                            f"Skipped page {current_page_number}, as data is already ingested."
                        )
                        continue

                    # Enable processing pages once ingested pages are skipped
                    process_pages = True
                    if current_page_number > 0:
                        logger.info(
                            f"Skipped all the pages from 0 to {current_page_number-1}, as data is already ingested."
                        )

                self._ckpt["page_number"] = current_page_number
                self.ingest_audit_service_data(self._items)

                # Update nextLink and corresponding page_number
                self._ckpt["nextLink"], self._ckpt["page_number"] = (
                    next_link,
                    self._ckpt["page_number"] + 1 if next_link else -1,
                )

                if not next_link:
                    break

            if not self._ckpt["is_migrated"]:
                self._legacy_checkpoint.close()
                self._legacy_checkpoint.delete(self._legacy_checkpoint._filename)
                logger.info(
                    "Successfully removed stale checkpoint file.", input_name=self._name
                )
                self._ckpt["is_migrated"] = True
        except Exception as ex:
            raise ex
        finally:
            self._collection.batch_save([self._ckpt])
            logger.info("Saved the checkpoint data.", checkpoint=self._ckpt)

    def get_batch_size(self):
        """
        This method used to get the max batch size from the limits.conf file
        By default it will return 1000 if not specified.

        Returns:
            int: return the max_documents_per_batch_save value from the conf file
        """
        batch_size: int = int(
            self._service.confs["limits"]["kvstore"].content.get(
                "max_documents_per_batch_save", 1000
            )
        )
        return batch_size

    def get_report_data(self):
        """
        This method used to communicate with portal and retreive the data
        For reports inputs.

        Returns:
            list[dict]: return list of events
        """
        reports = self._portal.o365_graph_api_report(self._endpoint["report_name"])
        items = reports.throttled_get(self._session)
        return items

    def ingest_report_data(self, items, batch_size):
        """This used the ingests and save checkpoint in the collection using batch calls.

        Args:
            items (list[dict]): list of events
            batch_size (int): max size of the batch list

        Raises:
            ex: if there is any exception, then raise it to parent method
        """
        try:
            batch_ckpt_list: list = []
            ingested_events_count = skipped_count = 0

            for event in items:
                key = self._endpoint.get("message_factory")(event)

                if self._collection.get(key):
                    logger.debug(f"Skipping the existing event : {key}")
                    skipped_count += 1
                else:
                    # add in a timestamp to each response item before recording to an event.
                    event.update(
                        {"timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
                    )
                    self.ingest(event)
                    ingested_events_count += 1

                    batch_ckpt_list.append(
                        {"_key": key, "expiration": int(self._time + 604800)}
                    )

                if len(batch_ckpt_list) == batch_size:
                    self._collection.batch_save(batch_ckpt_list)
                    batch_ckpt_list.clear()
        except Exception as ex:
            raise ex
        finally:
            if batch_ckpt_list:
                self._collection.batch_save(batch_ckpt_list)

            if ingested_events_count:
                logger.info("Successfully saved checkpoint data.")

            self._collection.delete({"expiration": {"$lt": self._time}})
            logger.debug("Stale Checkpoints swept Successfully")

            logger.info(
                "Total events summary.",
                received_events_count=len(items),
                skipped_count=skipped_count,
                ingested_events_count=ingested_events_count,
            )

    def report_data_collector(self, content_type):
        """
        This method used to collect the data of report endpoint input.

        Args:
            content_type (str): report endpoint content type
        """
        # update url for report endpoint inputs
        self._endpoint["report_name"] = self._endpoint["report_name"].format(
            content_type
        )
        # get the max batch save from limits.conf if specified else default 1000
        batch_size = self.get_batch_size()
        # Make the API call and get the report data
        items = self.get_report_data()
        # Ingest the report data
        self.ingest_report_data(items, batch_size)

    def run(self, content_type):
        """
        This method used to handle the flow input execution based on content-type of the input.
        It will also create the KVstore collection if not exists.

        Args:
            content_type (str): input content-type
        """
        try:
            self._time = self._now()

            logger.debug(
                "Start Retrieving Graph Api Messages.",
                timestamp=self._now(),
                report=content_type,
            )

            # Create Session Object
            self._session = self._proxy.create_requests_session()
            self._session = self._token.auth(self._session)

            # Load the input endpoint
            self._endpoint: dict = get_endpoint(content_type)

            if content_type.lower() in NON_REPORT_CONTENT_TYPES:
                # KVstore configuration
                self._ckpt_key: str = f"{content_type}_{self._name}"
                self.get_checkpoint_collection(self._endpoint["collection_name"])
                self._ckpt = self._collection.get(self._ckpt_key) or {
                    "_key": self._ckpt_key,
                    "event_count_offset": int(),
                    "last_event_timestamp": str(),
                    "is_migrated": bool(),
                    "nextLink": str(),
                    "page_number": -1,
                }
                logger.debug("Current checkpoint.", current_checkpoint=self._ckpt)

                # Collect the Audit and ServiceAnnouncement data
                self.audit_service_data_collector()
            else:
                # KVStore Configuration
                collection_name: str = f"splunk_ta_o365_{content_type}_{self._name}"
                self.get_checkpoint_collection(collection_name)

                # Collect the data
                self.report_data_collector(content_type)
                # Delete the legacy checkpoint
                self.delete_legacy_report_checkpoint()

            logger.debug(
                "End Retrieving Graph Api Messages.",
                timestamp=self._now(),
                report=content_type,
            )
        except Exception as e:
            logger.error("Error retrieving Graph API Messages.", exception=e)
            raise

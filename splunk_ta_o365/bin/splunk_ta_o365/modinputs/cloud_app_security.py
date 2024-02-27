#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import platform
import time
from datetime import datetime

from splunk_ta_o365.common.portal import O365PortalRegistry
from splunk_ta_o365.common.settings import Logging, Proxy
from splunk_ta_o365.common.tenant import O365Tenant
from splunksdc import logging
from splunksdc.checkpoint import Partition
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import StanzaParser, StringField
from splunksdc.utils import LogExceptions, LogWith

logger = logging.get_module_logger()

"""
    class CloudApplicationSecurityMessageConsumer
    This class is used to make calls to the Microsoft Cloud Application APIs to retrieve data/reports and then ingest
    the events using an eventwriter to splunk.
"""


class CloudApplicationSecurityMessageConsumer:
    def __init__(self, checkpoint, event_writer, portal, session, policy, report):
        self._checkpoint = Partition(checkpoint, "/v1/")
        self._event_writer = event_writer
        self._portal = portal
        self._session = session
        self._report = report
        self._now = time.time
        self._cas_portal_url = policy.cas_portal_url
        self._cas_portal_data_center = policy.cas_portal_data_center

    def run(self):
        now = self._now()
        update_time = datetime.utcfromtimestamp(now)
        try:
            reports = self._portal.o365_cloud_app_security_call(
                update_time,
                self._report,
                self._cas_portal_url,
                self._cas_portal_data_center,
            )

            source = reports.source

            logger.info(
                "Start recording Cloud Application Security messages.", source=source
            )
            for message in reports.throttled_get(self._session):
                key = self._make_unique_key(message)
                if not self._checkpoint.find(key):
                    self._ingest(message, source)
                # self._sweep_checkpoint()

        except Exception as e:
            logger.info(
                "Error retrieving Cloud Application Security messages.", exception=e
            )
            raise

    def _ingest(self, message, source):
        key = self._make_unique_key(message)
        self._event_writer.write_event(message.data, message.update_time, source=source)
        expiration = int(self._now() + 604800)  # keeping expiration for 7 days
        self._checkpoint.set(key, expiration)

    # Commenting the _sweep_checkpoint logic for now, since API is not consistent
    # on filter logic which is still causing the duplication of data.
    # To avoid this we will not delete the checkpoint info till we find
    # the fix (disclaimer: checkpoint's file size may be slightly larger than expected)

    # def _sweep_checkpoint(self):
    #     now = self._now()
    #     checkpoint = self._checkpoint
    #     expired = [
    #         key for key, expiration in list(checkpoint.items()) if now > expiration
    #     ]
    #     for key in expired:
    #         checkpoint.delete(key)
    #     checkpoint.sweep()

    @classmethod
    def _make_unique_key(cls, message):
        return f"{message.id}-{message.update_time}"


"""
    class DataInput
    This class sets up the modular input including setting up report names (content_type), authentication,
    proxy and other session information.
"""


class DataInput:
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
                StringField("sourcetype", default="o365:cas:api"),
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

    def _get_content_type(self):
        parser = StanzaParser(
            [
                StringField("content_type"),
            ]
        )
        args = self._extract_arguments(parser)
        return args.content_type

    def _create_tenant(self, config):
        tenant_name = self._get_tenant_name()
        return O365Tenant.create(config, tenant_name)

    def _create_event_writer(self, app):
        metadata = self._create_metadata()
        return app.create_event_writer(None, **vars(metadata))

    def _extract_arguments(self, parser):
        return parser.parse(self._args)

    """
        def _create_consumer(
        1)  Create a consumer for the select report by content_type.
        2)  Update the report name and return a new CloudApplicationSecurityMessageConsumer if it was
        a mapped selection.
        3)  The report names will be appended to the path for the cloud application security portal api calls.
    """

    def _create_consumer(self, checkpoint, event_writer, portal, session, policy):
        parser = StanzaParser(
            [
                StringField("content_type"),
            ]
        )
        args = self._extract_arguments(parser)
        content_type = args.content_type.lower()
        report_name = ""

        logger.info(
            "Start retrieving Cloud Application Security messages.",
            portal_url=policy.cas_portal_url,
            portal_region=policy.cas_portal_data_center,
        )

        if content_type.find("policies") != -1:
            report_name = "policies"

        if content_type.find("alerts") != -1:
            report_name = "alerts"

        if content_type.find("cloud discovery") != -1:
            report_name = "discovery"

        if content_type.find("entities") != -1:
            report_name = "entities"

        if content_type.find("files") != -1:
            report_name = "files"

        return CloudApplicationSecurityMessageConsumer(
            checkpoint, event_writer, portal, session, policy, report_name
        )

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
        cas = tenant.create_cas_portal(registry)
        policy = tenant.create_cas_token_policy(registry)
        token = cas.create_cas_token_provider(policy)
        portal = cas.get_cas_portal_communications()
        session = proxy.create_requests_session()
        session = token.auth(session)
        event_writer = self._create_event_writer(app)
        with app.open_checkpoint(self.name) as checkpoint:
            checkpoint.sweep()
            consumer = self._create_consumer(
                checkpoint, event_writer, portal, session, policy
            )
            return consumer.run()


"""
    def modular_input_run
    1)  Returns the output from the class DataInput
    2)  This will trigger calls to the Microsoft Cloud Application Security API to get data/input related to the
    content_type specified.
"""


def modular_input_run(app, config):
    array = app.inputs()
    di = DataInput(array[0])
    return di.run(app, config)


"""
    def main
    Accepts arguments for the tenant_name and content_type and runs SimpleCollectorV1 to ingest service messages
    from the Microsoft Cloud Application Security API.
"""


def main():

    arguments = {
        "tenant_name": {
            "title": "Tenant Name",
            "description": "Which Office 365 tenant will be used.",
        },
        "content_type": {
            "title": "Content Type",
            "description": "What kind of Report/Endpoint will be ingested.",
        },
    }

    SimpleCollectorV1.main(
        modular_input_run,
        title="Splunk Add-on for Microsoft Office 365: Cloud Application Security",
        description="Ingest service messages from Microsoft Cloud Application Security API",
        use_single_instance=False,
        arguments=arguments,
    )

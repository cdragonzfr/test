#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import time
import platform
from splunksdc import logging
from splunksdc.utils import LogExceptions, LogWith
from splunksdc.config import StanzaParser, StringField, IntegerField
from splunksdc.collector import SimpleCollectorV1
from splunk_ta_o365.common.portal import O365PortalRegistry
from splunk_ta_o365.common.tenant import O365Tenant
from splunk_ta_o365.common.settings import Proxy, Logging

from splunk_ta_o365.modinputs.graph_api.GraphApiConsumer import GraphApiConsumer as gac

logger = logging.get_module_logger()

"""
    class DataInput
    This class sets up the modular input including setting up report names (content_type), authentication, proxy and other session information.
"""


class GraphApiModInput(object):
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
                StringField("sourcetype", default="o365:graph:api"),
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

    def _get_request_timeout(self):
        parser = StanzaParser([IntegerField("request_timeout", default=60)])
        args = self._extract_arguments(parser)
        return args.request_timeout

    def _create_tenant(self, config):
        tenant_name = self._get_tenant_name()
        return O365Tenant.create(config, tenant_name)

    def _create_event_writer(self, app):
        metadata = self._create_metadata()
        return app.create_event_writer(None, **vars(metadata))

    def _extract_arguments(self, parser):
        return parser.parse(self._args)

    """
        def _create_consumer
        1)  Create a consumer for the select report by content_type.
        2)  Update the report name and return a new GraphMessageAuditConsumer or GraphMessageReportConsumer depending on if it was a mapped selection.
        3)  The report names will be appended to the path for the microsoft graph api calls.
    """

    def _create_consumer(self, app, config, event_writer, portal, proxy, token):
        return gac(self.name, app, config, event_writer, portal, proxy, token)

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
        graph = tenant.create_graph_portal(registry)
        policy = tenant.create_v2_token_policy(registry)
        token = graph.create_graph_token_provider(policy)
        request_timeout = self._get_request_timeout()
        portal = graph.get_graph_portal_communications(request_timeout)
        content_type = self._get_content_type()
        event_writer = self._create_event_writer(app)

        consumer = self._create_consumer(
            app, config, event_writer, portal, proxy, token
        )
        consumer.run(content_type)

        return 0


def modular_input_run(app, config):
    """This method will trigger calls to the Microsoft Graph API to get data/input related to the content_type specified.

    Args:
        app (SimpleCollectorV1): Object of splunksdc.collector.SimpleCollectorV1
        config (ConfigManager): Object of splunksdc.config.ConfigManager

    Returns:
        Returns the output from the class DataInput
    """
    array = app.inputs()
    di = GraphApiModInput(array[0])
    return di.run(app, config)


def main():
    """
    Accepts arguments for the tenant_name and content_type,
    Runs SimpleCollectorV1 to ingest service messages from the Microsoft Graph API.
    """
    arguments = {
        "tenant_name": {
            "title": "Tenant Name",
            "description": "Which Office 365 tenant will be used.",
        },
        "content_type": {
            "title": "Content Type",
            "description": "What kind of Report/Endpoint will be ingested.",
        },
        "request_timeout": {
            "title": "Request Timeout",
            "description": "How much amount of time (in seconds) to wait for a response from the API",
        },
    }

    SimpleCollectorV1.main(
        modular_input_run,
        title="Splunk Add-on for Microsoft Office 365: Graph API Reports",
        description="Ingest service messages from Microsoft Graph API",
        use_single_instance=False,
        arguments=arguments,
    )

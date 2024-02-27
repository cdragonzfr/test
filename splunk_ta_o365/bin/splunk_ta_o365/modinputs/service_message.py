#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#


from splunksdc import logging
from splunksdc.collector import SimpleCollectorV1


logger = logging.get_module_logger()


def modular_input_run(app, config):
    logger.warn("Splunk Add-on for Microsoft Office 365 Service Message has be retired")
    return True


def main():
    arguments = {
        "tenant_name": {
            "title": "Tenant Name",
            "description": "Which Office 365 tenant will be used.",
        },
    }

    SimpleCollectorV1.main(
        modular_input_run,
        title="Splunk Add-on for Microsoft Office 365 Service Message",
        description="(Retired) Ingest service messages from Office 365 Service Communications API",
        use_single_instance=False,
        arguments=arguments,
    )

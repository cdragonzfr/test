#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
"""
This is the main entry point for My TA
"""
import import_declare_test
import splunktaucclib.data_collection.ta_mod_input as ta_input
from mscs_storage_blob_data_client import StorageBlobDataClient as collector_cls
from mscs_util import get_schema_file_path, setup_log_level


def ta_run():
    setup_log_level()
    schema_file_path = get_schema_file_path("mscs_schema.storage_blob_config.json")
    ta_input.main(
        collector_cls,
        schema_file_path,
        "storage_blob",
        schema_para_list=(
            "description",
            "account",
            "container_name",
            "prefix",
            "blob_list",
            "collection_interval",
            "exclude_blob_list",
            "blob_mode",
            "is_migrated",
            "decoding",
            "log_type",
            "guids",
            "application_insights",
            "blob_input_help_link",
        ),
        single_instance=False,
    )


if __name__ == "__main__":
    ta_run()

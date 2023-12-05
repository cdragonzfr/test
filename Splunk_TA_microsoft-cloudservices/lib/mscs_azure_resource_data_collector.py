#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from builtins import str
from builtins import object
import json

import mscs_api_error as mae
import mscs_azure_base_data_collector as mabdc
import mscs_consts
import splunktaucclib.data_collection.ta_data_client as dc


_RESOURCE_NOT_FOUND = "ResourceNotFound"
_RESOURCE_GROUP_NOT_FOUND = "ResourceGroupNotFound"


@dc.client_adapter
def do_job_one_time(all_conf_contents, task_config, ckpt):
    collector = AzureResourceDataCollector(all_conf_contents, task_config)
    return collector.collect_data()


class AzureResourceType(object):
    VIRTUAL_MACHINE = "virtual_machine"
    PUBLIC_IP_ADDRESS = "public_ip_address"


class AzureResourceDataCollector(mabdc.AzureBaseDataCollector):
    def __init__(self, all_conf_contents, task_config):
        super(AzureResourceDataCollector, self).__init__(all_conf_contents, task_config)
        self._resource_type = task_config[mscs_consts.RESOURCE_TYPE]
        self._resource_group_list_str = task_config.get(mscs_consts.RESOURCE_GROUP_LIST)
        self._index = task_config[mscs_consts.INDEX]

        self._parse_api_setting(self._resource_type)

    def collect_data(self):
        self._logger.info("Starting to collect data.")

        resource_group_list = self._get_resource_group_list()

        self._logger.info("The resource_group_list=%s", resource_group_list)
        self._logger.info("The resource_type=%s", self._resource_type)

        for resource_group in resource_group_list:
            try:
                next_link = None
                while True:
                    url = self._generate_url(
                        resource_group=resource_group, next_link=next_link
                    )
                    self._logger.debug("Sending request url=%s", url)

                    result = self._perform_request(url)
                    # get vm info list
                    if self._resource_type == AzureResourceType.VIRTUAL_MACHINE:
                        resource_info_lst = self._get_detailed_vm_info_list(
                            resource_group, result.get("value")
                        )
                    else:
                        resource_info_lst = result.get("value")
                    events = self._convert_resource_info_list_to_events(
                        resource_info_lst
                    )
                    stop = yield events, None
                    if stop:
                        self._logger.info("Received the stop signal.")
                        return
                    # check next_link
                    next_link = result.get(self._NEXT_LINK)
                    if not next_link:
                        break
            except mae.APIError as e:
                if e.error_code == _RESOURCE_GROUP_NOT_FOUND:
                    self._logger.warning("Resource group not found: %s", str(e))
                else:
                    raise e

        self._logger.info("Finishing collect data.")

    def _parse_api_setting(self, api_stanza_name):
        api_setting = super(AzureResourceDataCollector, self)._parse_api_setting(
            api_stanza_name
        )
        if self._resource_type == AzureResourceType.VIRTUAL_MACHINE:
            self._instance_view_url = api_setting[mscs_consts.INSTANCE_VIEW_URL]
        return api_setting

    def _get_logger_prefix(self):
        account_stanza_name = self._task_config[mscs_consts.ACCOUNT]
        pairs = [
            '{}="{}"'.format(
                mscs_consts.STANZA_NAME, self._task_config[mscs_consts.STANZA_NAME]
            ),
            '{}="{}"'.format(mscs_consts.ACCOUNT, account_stanza_name),
            '{}="{}"'.format(
                mscs_consts.RESOURCE_TYPE, self._task_config[mscs_consts.RESOURCE_TYPE]
            ),
        ]
        return "[{}]".format(" ".join(pairs))

    def _get_resource_group_list(self):
        if not self._resource_group_list_str:
            resource_groups = self._resource_client.resource_groups.list()
            return [group.name for group in resource_groups]
        else:
            return [
                resource_group.strip()
                for resource_group in self._resource_group_list_str.split(",")
                if len(resource_group.strip())
            ]

    def _get_detailed_vm_info_list(self, resource_group, vm_info_lst):
        for vm_info in vm_info_lst:
            try:
                vm_name = vm_info["name"]
                url = self._generate_url(resource_group=resource_group, vm_name=vm_name)
                result = self._perform_request(url)
                vm_info["properties"]["instanceView"] = result
                tags = vm_info.get("tags")
                if not tags:
                    continue
                tag_lst = []
                for (tag_k, tag_v) in tags.items():
                    tag_lst.append(tag_k + " : " + tag_v)
                vm_info["tags"] = tag_lst
            except mae.APIError as e:
                if e.error_code == _RESOURCE_NOT_FOUND:
                    self._logger.warning("Resource not found: %s", str(e))
                else:
                    raise e
        return vm_info_lst

    def _generate_url(self, resource_group, vm_name=None, next_link=None):
        if next_link:
            return next_link
        if not vm_name:
            return self._url.format(
                subscription_id=self._subscription_id,
                resource_group_name=resource_group,
                api_version=self._api_version,
                base_host=self._manager_url,
            )
        else:
            return self._instance_view_url.format(
                subscription_id=self._subscription_id,
                resource_group_name=resource_group,
                vm_name=vm_name,
                api_version=self._api_version,
                base_host=self._manager_url,
            )

    def _convert_resource_info_list_to_events(self, resource_info_lst):
        events = []
        for resource_info in resource_info_lst:
            events.append(
                dc.build_event(
                    sourcetype=self._sourcetype,
                    source=resource_info["id"],
                    index=self._index,
                    raw_data=json.dumps(resource_info),
                )
            )
        return events

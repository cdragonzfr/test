#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from datetime import datetime
from splunktaucclib.rest_handler.endpoint import validator


class UTCDateValidator(validator.Validator):
    def __init__(self):
        super(UTCDateValidator, self).__init__()

    def validate(self, value, data):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
            return True
        except ValueError:
            self.put_msg("Valid Datetime format is 'YYYY-MM-DDTHH:MM:SS'")
            return False


def graph_api_list_remove_item(confInfo, contentTypes):
    """This method is used to remove the content types from the list of inputs which are not part of
    the specific rest handler of graph_api. The graph_api resh handlers has common stanza for the inputs
    because of which it shows duplicate entries on the input page table. Hence this method implementation
    to return input entries only specific to particular rest handler based on content type.

    Args:
        confInfo (_type_): _description_
        contentTypes (_type_): list of content types of particular input type
    """

    config_items_copy = confInfo.data.copy()
    for key, value in config_items_copy.items():
        content_type = value.data.get("content_type")
        if not content_type in contentTypes:
            del confInfo.data[key]

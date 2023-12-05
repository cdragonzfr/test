#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
"""
This module will be used to validate the if the account is valid or not
"""
import import_declare_test
import splunk.admin as admin
from solnlib import log
from solnlib import conf_manager
from future import standard_library

standard_library.install_aliases()

log.Logs.set_context()
logger = log.Logs().get_logger("splunk_ta_mscs_rh_check_account_configuration")

"""
REST Endpoint to validate the if the account is valid or not
"""


class AccountCheckConfigurationHandler(admin.MConfigHandler):

    """
    This method checks which action is getting called and what parameters are required for the request.
    """

    def setup(self):
        if self.requestedAction == admin.ACTION_LIST:
            # Add required args in supported args
            self.supportedArgs.addReqArg("account_name")
            self.supportedArgs.addReqArg("account_type")
        return

    """
    This handler is to validate the if the account is valid or not
    It takes 'account_name' and 'account_type' as caller args and
    Returns the confInfo dict object in response.
    """

    def handleList(self, confInfo):
        logger.info("Entering handler to check account configuration")
        # Get args parameters from the request
        account_name = self.callerArgs.data["account_name"][0]
        account_type = self.callerArgs.data["account_type"][0]
        if account_type.lower() == "storage":
            configuration_file = "mscs_storage_accounts"
            credential_field = "account_secret"
        elif account_type.lower() == "azure":
            configuration_file = "mscs_azure_accounts"
            credential_field = "client_secret"
        else:
            raise ValueError(
                'Invalid account type. Supported types = ["storage", "azure"]'
            )

        cfm = conf_manager.ConfManager(
            self.getSessionKey(),
            "Splunk_TA_microsoft-cloudservices",
            realm="__REST_CREDENTIAL__#Splunk_TA_microsoft-cloudservices#configs/conf-{}".format(
                configuration_file
            ),
        )
        conf = cfm.get_conf(configuration_file)
        account_stanza = conf.get(account_name, only_current_app=True)
        account_secret = account_stanza.get(credential_field)
        if account_secret == "*" * 8:
            confInfo["account"]["isvalid"] = "false"
        else:
            confInfo["account"]["isvalid"] = "true"
        confInfo["account"]["name"] = account_name
        confInfo["account"]["type"] = account_type
        confInfo["account"]["secret"] = account_secret
        logger.info("Exiting handler to check account configuration")


if __name__ == "__main__":
    admin.init(AccountCheckConfigurationHandler, admin.CONTEXT_APP_AND_USER)

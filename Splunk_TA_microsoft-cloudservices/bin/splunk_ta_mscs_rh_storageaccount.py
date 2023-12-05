#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import import_declare_test  # noqa: F401 # isort:skip
import logging
import traceback
from builtins import next, str

from splunktaucclib.rest_handler import (  # isort: skip # pylint: disable=import-error
    admin_external,
    util,
)
from splunktaucclib.rest_handler.admin_external import (  # isort: skip # pylint: disable=import-error
    AdminExternalHandler,
)

from mscs_storage_service import (  # isort:skip # pylint: disable=import-error
    AccountSecretType,
    StorageService,
    _create_blob_service,
    _create_table_service,
)
from mscs_util import (  # isort:skip # pylint: disable=import-error
    check_account_isvalid,
    get_logger,
    get_proxy_info_from_endpoint,
    make_proxy_url,
    mscs_consts,
)
from splunktaucclib.rest_handler.endpoint import (  # isort:skip # pylint: disable=import-error
    RestModel,
    SingleModel,
    field,
    validator,
)

util.remove_http_proxy_env_vars()


def get_proxy_dict(proxy_config):
    """Get the proxy for the BlobServiceClient.

    :param proxy_config: Dictionary containing proxy details
    :param service: Object of the class BlobServiceClient
    """
    proxy_url = make_proxy_url(
        host=proxy_config[mscs_consts.PROXY_URL],
        port=proxy_config[mscs_consts.PROXY_PORT],
        user=proxy_config.get(mscs_consts.PROXY_USERNAME),
        password=proxy_config.get(mscs_consts.PROXY_PASSWORD),
    )

    # Overwriting proxy for https scheme to http (To resolve urllib3 v1.26.5 version update failure)
    proxy_dict = {"https": proxy_url, "http": proxy_url}
    return proxy_dict


class StorageAccountValidation(validator.Validator):
    def __init__(self):
        super(StorageAccountValidation, self).__init__()

        self.account_name = None
        self.account_class_type = None
        self.account_secret = None
        self.account_secret_type = None
        self.proxy_config = None

    def validate(self, value, data):
        """Validate the given values.

        :param value: Value of particular parameter
        :param data: Whole payload
        :return: True if validation pass, False otherwise.
        """

        logger = get_logger(
            "splunk_ta_microsoft-cloudservices_storage_account_validation"
        )

        logger.info("Verifying credentials for the MSCS Storage account")

        self.account_name = data.get(mscs_consts.ACCOUNT_NAME)
        self.account_secret_type = data.get(mscs_consts.ACCOUNT_SECRET_TYPE)
        self.account_class_type = data.get(mscs_consts.ACCOUNT_CLASS_TYPE)

        # If secret type is not "None Secret", account_secret is required
        # Otherwise don't validate and directly return True
        if self.account_secret_type != "0":
            self.account_secret = data.get(mscs_consts.ACCOUNT_SECRET)
            if not self.account_secret:
                self.put_msg("Field Account Secret is required")
                return False

            # For account secret type "Account Token", token generated on Azure has
            # ? on start, but we have to pass the token without "?". So remove it if
            # account secret is starting with ?
            if self.account_secret_type == str(AccountSecretType.SAS_TOKEN):
                self.account_secret = StorageService._process_sas_token(
                    self.account_secret
                )
        else:
            return True

        error_message = (
            "Account authentication failed. Please check your credentials and try again"
        )

        proxies = None
        logger.info("Getting proxy details")
        # Get proxy details and return False if any issue occurs while getting the details
        try:
            self.proxy_config = get_proxy_info_from_endpoint()
        except Exception as e:
            logger.error(
                "Error {} while getting proxy details: {}".format(
                    e, traceback.format_exc()
                )
            )
            self.put_msg(error_message)
            return False

        # If proxy details are available and proxy is enabled
        if (
            self.proxy_config.get(mscs_consts.PROXY_ENABLED)
            and self.proxy_config[mscs_consts.PROXY_ENABLED] != "0"
        ):

            logger.info("Proxy is enabled")
            # Both proxy_url and proxy_port are provided
            if not all(
                (
                    self.proxy_config.get(mscs_consts.PROXY_URL),
                    self.proxy_config.get(mscs_consts.PROXY_PORT),
                )
            ):
                logger.error("Proxy host or port is invalid")
                self.put_msg(error_message)
                return False

            # Hook the proxy with the object
            try:
                logger.info(
                    "Changing proxy schemes to http as only http proxy is supported"
                )
                proxies = get_proxy_dict(self.proxy_config)
            except Exception as e:
                self.put_msg(error_message)
                logger.error(
                    "Error {} while setting the proxy: {}".format(
                        e, traceback.format_exc()
                    )
                )
                return False

        # Create the object of class BlobServiceClient and TableServiceClient
        try:
            blob_service_client = _create_blob_service(
                account_name=self.account_name,
                account_secret_type=int(self.account_secret_type),
                account_secret=self.account_secret,
                account_class_type=int(self.account_class_type),
                proxies=proxies,
            )
            table_service = _create_table_service(
                account_name=self.account_name,
                account_secret_type=int(self.account_secret_type),
                account_secret=self.account_secret,
                account_class_type=int(self.account_class_type),
                proxies=proxies,
            )
        except Exception as e:
            logger.error(
                "Error {} while verifying the credentials: {}".format(
                    e, traceback.format_exc()
                )
            )
            self.put_msg(error_message)
            return False

        # Verify the credentials, pass num_results=1 so that it does not return much data
        try:
            PagedContainers = blob_service_client.list_containers(results_per_page=1)
            PagedContainers.next()
        except StopIteration:
            pass
        except Exception as e:
            self.put_msg(error_message)
            logger.error(
                "Error {} while verifying the credentials: {}".format(
                    e, traceback.format_exc()
                )
            )
            return False

        try:
            PagedTables = table_service.list_tables(results_per_page=1)
            PagedTables.next()
        except StopIteration:
            pass
        except Exception as e:
            self.put_msg(error_message)
            logger.error(
                "Error {} while verifying the credentials: {}".format(
                    e, traceback.format_exc()
                )
            )
            return False

        logger.info("Credentials validated successfully")
        return True


class StorageAccountHandler(AdminExternalHandler):
    """
    This handler is to check if the account configurations are valid or not
    """

    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)
        check_account_isvalid(confInfo, self.getSessionKey(), account_type="storage")

    def handleEdit(self, confInfo):
        AdminExternalHandler.handleEdit(self, confInfo)
        edited_account = next(iter(confInfo))
        confInfo[edited_account]["isvalid"] = "true"

    def handleCreate(self, confInfo):
        AdminExternalHandler.handleCreate(self, confInfo)
        edited_account = next(iter(confInfo))
        confInfo[edited_account]["isvalid"] = "true"


fields = [
    field.RestField(
        "account_name", required=True, encrypted=False, default=None, validator=None
    ),
    field.RestField(
        "account_secret", required=False, encrypted=True, default=None, validator=None
    ),
    field.RestField(
        "account_secret_type",
        required=True,
        encrypted=False,
        default="1",
        validator=None,
    ),
    field.RestField(
        "account_class_type",
        required=True,
        encrypted=False,
        default="1",
        validator=StorageAccountValidation(),
    ),
    field.RestField(
        "storage_account_help_link",
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


endpoint = SingleModel("mscs_storage_accounts", model, config_name="storageaccount")


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=StorageAccountHandler,
    )

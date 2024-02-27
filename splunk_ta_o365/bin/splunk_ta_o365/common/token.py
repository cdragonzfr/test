#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import time


class O365Token:
    def __init__(self, token_type, access_token, expires_on, **kwargs):
        self._token_type = token_type
        self._access_token = access_token
        self._expires_on = int(expires_on)
        self._now = time.time

    def ttl(self):
        return self._expires_on - self._now()

    # jscpd:ignore-start

    def need_retire(self, min_ttl):
        return self.ttl() < min_ttl

    @property
    def token_type(self):
        return self._token_type

    @property
    def access_token(self):
        return self._access_token

    @property
    def expires_on(self):
        return self._expires_on

    # jscpd:ignore-end


class GraphToken:
    def __init__(self, token_type, access_token, expires_in, **kwargs):
        self._token_type = token_type
        self._access_token = access_token
        self._expires_in = int(expires_in)
        self._now = time.time
        self._expires_on = self._now() + self._expires_in

    # jscpd:ignore-start

    def ttl(self):
        return self._expires_on - self._now()

    def need_retire(self, min_ttl):
        return self.ttl() < min_ttl

    @property
    def token_type(self):
        return self._token_type

    @property
    def access_token(self):
        return self._access_token

    @property
    def expires_on(self):
        return self._expires_on

    @property
    def expires_in(self):
        return self._expires_in

    # jscpd:ignore-end


class CasToken:
    def __init__(
        self, token_type, access_token, cas_portal_url, cas_portal_data_center, **kwargs
    ):
        self._token_type = token_type
        self._access_token = access_token
        self._cas_portal_url = cas_portal_url
        self._cas_portal_data_center = cas_portal_data_center

    @property
    def token_type(self):
        return self._token_type

    @property
    def access_token(self):
        return self._access_token

    @property
    def cas_portal_url(self):
        return self._cas_portal_url

    @property
    def cas_portal_data_center(self):
        return self._cas_portal_data_center


class MessageTraceToken:
    def __init__(self, token_type, access_token, expires_in, **kwargs):
        self._token_type = token_type
        self._access_token = access_token
        self._expires_in = int(expires_in)
        self._now = time.time
        self._expires_on = self._now() + self._expires_in

    def ttl(self):
        return self._expires_on - self._now()

    def need_retire(self, min_ttl):
        return self.ttl() < min_ttl

    @property
    def token_type(self):
        return self._token_type

    @property
    def access_token(self):
        return self._access_token

    @property
    def expires_on(self):
        return self._expires_on

    @property
    def expires_in(self):
        return self._expires_in


class O365v2TokenPSKPolicy:
    def __init__(self, portal, client_id, client_secret):
        self._portal = portal
        self._client_id = client_id
        self._client_secret = client_secret

    def __call__(self, resource, session):
        return self._portal.get_v2_token_by_psk(
            self._client_id, self._client_secret, resource, session
        )


class O365CloudAppSecurityPSKPolicy:
    def __init__(
        self,
        portal,
        tenant_id,
        cloudappsecuritytoken,
        cas_portal_url,
        cas_portal_data_center,
    ):
        self._portal = portal
        self._cloudappsecuritytoken = cloudappsecuritytoken
        self._cas_portal_url = cas_portal_url
        self._cas_portal_data_center = cas_portal_data_center

    @property
    def cas_portal_url(self):
        return self._cas_portal_url

    @property
    def cas_portal_data_center(self):
        return self._cas_portal_data_center

    def __call__(self, resource, session):  # pylint: disable=unused-argument
        return self._portal.get_cas_token_by_psk(
            self._cloudappsecuritytoken,
            self._cas_portal_url,
            self._cas_portal_data_center,
        )


class O365MessageTracePSKPolicy:
    def __init__(self, portal, client_id, client_secret):
        self._portal = portal
        self._client_id = client_id
        self._client_secret = client_secret

    def __call__(self, resource, session):
        return self._portal.get_messagetrace_token_by_psk(
            self._client_id, self._client_secret, resource, session
        )


class O365TokenProvider:
    def __init__(self, resource, policy):
        self._resource = resource
        self._policy = policy
        self._token = None

    def set_auth_header(self, session):
        session.headers.update(
            {
                "Authorization": "{} {}".format(
                    self._token.token_type, self._token.access_token
                )
            }
        )
        return session

    def auth(self, session):
        self._token = self._policy(self._resource, session)
        return self.set_auth_header(session)

    def need_retire(self, min_ttl):
        if not self._token:
            return True
        return self._token.need_retire(min_ttl)

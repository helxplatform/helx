from django.apps import AppConfig
from django.conf import settings


class AppsCoreServicesConfig(AppConfig):
    name = 'core'

    def ready(self):
        import core.signals
        self._pin_saml_sp_entity_id()

    @staticmethod
    def _pin_saml_sp_entity_id():
        # Allauth-SAML derives the SP `entityId` and ACS URL from the per-org
        # metadata/ACS URLs it serves at runtime. Both diverge from what the
        # IdP has registered for this service (the legacy
        # `https://<host>/saml2_auth/acs/` ACS path and corresponding entity
        # ID). The IdP rejects AuthnRequests whose Issuer or ACS URL don't
        # match its registration, so we monkey-patch `build_sp_config` to
        # pin both to the configured legacy values. The metadata endpoint
        # uses the same builder, so the SP metadata advertised to the IdP
        # stays internally consistent.
        if getattr(settings, "ALLOW_SAML_LOGIN", "").lower() != "true":
            return
        sp_entity_id = getattr(settings, "SAML_SP_ENTITY_ID", None)
        sp_acs_url = getattr(settings, "SAML_SP_ACS_URL", None)
        if not sp_entity_id and not sp_acs_url:
            return
        from allauth.socialaccount.providers.saml import utils as saml_utils
        original = saml_utils.build_sp_config

        def build_sp_config_pinned(request, provider_config, org):
            config = original(request, provider_config, org)
            if sp_entity_id:
                config["entityId"] = sp_entity_id
            if sp_acs_url:
                config["assertionConsumerService"]["url"] = sp_acs_url
            return config

        saml_utils.build_sp_config = build_sp_config_pinned
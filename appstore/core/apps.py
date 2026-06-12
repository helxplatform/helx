from django.apps import AppConfig
from django.conf import settings


class AppsCoreServicesConfig(AppConfig):
    name = 'core'

    def ready(self):
        import core.signals
        self._pin_saml_sp_entity_id()

    @staticmethod
    def _pin_saml_sp_entity_id():
        # Allauth-SAML derives the SP `entityId` from the per-org metadata
        # URL it serves at runtime. That diverges from the SP entity ID the
        # IdP has registered for this service (the legacy
        # `https://<host>/saml2_auth/acs/` value). The IdP rejects an
        # AuthnRequest whose Issuer doesn't match the registered SP entity
        # ID, so we monkey-patch `build_sp_config` to pin entityId to the
        # configured value. The metadata endpoint uses the same builder, so
        # the SP metadata advertised to the IdP stays consistent.
        if getattr(settings, "ALLOW_SAML_LOGIN", "").lower() != "true":
            return
        sp_entity_id = getattr(settings, "SAML_SP_ENTITY_ID", None)
        if not sp_entity_id:
            return
        from allauth.socialaccount.providers.saml import utils as saml_utils
        original = saml_utils.build_sp_config

        def build_sp_config_pinned(request, provider_config, org):
            config = original(request, provider_config, org)
            config["entityId"] = sp_entity_id
            return config

        saml_utils.build_sp_config = build_sp_config_pinned
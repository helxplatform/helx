from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import RedirectView
from django.views.static import serve

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import custom404
from frontend.views import HelxLoginView
admin.autodiscover()

handler404 = custom404


def _saml_legacy_login(request):
    # Legacy entry point preserved so existing IdP metadata and external
    # links continue to resolve. Dispatches to allauth-SAML's login view
    # under the configured organization slug.
    from allauth.socialaccount.providers.saml import views as saml_views
    return saml_views.login(request, organization_slug=settings.SAML_PROVIDER_SLUG)


@csrf_exempt
def _saml_legacy_acs(request):
    # Legacy ACS endpoint preserved so the IdP can POST SAMLResponses to
    # the same URL it was configured with under django-saml2-auth. A redirect
    # would convert the POST to a GET and drop the assertion, so we invoke
    # the allauth-SAML ACS view in-process instead. csrf_exempt is required
    # on this outer wrapper because Django's CSRF middleware checks the
    # exemption attribute on the URL-resolved callback, not the inner view.
    from allauth.socialaccount.providers.saml import views as saml_views
    return saml_views.acs(request, organization_slug=settings.SAML_PROVIDER_SLUG)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("saml2_auth/acs/", _saml_legacy_acs),
    path("accounts/saml/", _saml_legacy_login),
    path(r"accounts/login/", HelxLoginView.as_view(), name="helx_login"),
    path("accounts/", include("allauth.urls")),
]

urlpatterns += [
    path("", include("core.urls")),
    path("", include("api.urls")),
    path("", include("frontend.urls")),
]

urlpatterns += [
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="swagger-ui",
    ),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/images/favicon.ico", permanent=True),
        name="favicon",
    ),
    re_path("static/(?P<path>.*)", serve, {"document_root": settings.STATIC_ROOT}),
]

# Django debug toolbar, reference settings/base.py INTERNAL_IP and associated
# settings
if settings.DEBUG:
    # don't import or load the toolbar paths unless in debug
    import debug_toolbar

    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]

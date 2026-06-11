import secrets
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session as SessionModel
from django.core.exceptions import ValidationError
from django_saml2_auth.user import get_user, get_user_id
from datetime import timedelta
from string import ascii_letters, digits, punctuation

UserModel = get_user_model()


# Provider key used for the allauth SocialAccount row that links a SAML
# identity (the assertion uid / onyen) to a Django user. This gives SAML users
# a stable identity independent of their username, so resolution never depends
# on the (shared, collidable) username namespace.
SAML_PROVIDER = "saml"


def saml_get_user(user):
    # TRIGGER.GET_USER hook for django_saml2_auth. Decides which existing
    # account, if any, a SAML login resolves to. The library's default is to log
    # into ANY user whose username equals the assertion uid, with no identity
    # check -- a takeover risk once accounts are also created via allauth/Google,
    # and it cannot give a stable account to a user whose uid collides with a
    # different person's username.
    #
    # We resolve by a stable SocialAccount(provider="saml", uid) link instead of
    # by username. Order:
    #   1. Linked SAML identity exists -> return its user (username-independent).
    #   2. Verified-email merge (only if this IdP is trusted): assertion email
    #      matches an account's verified allauth EmailAddress -> link this SAML
    #      identity to that account and return it.
    #   3. Legacy SAML user predating the link: a user whose username equals the
    #      uid and has no SocialAccount -> adopt it and backfill the link.
    #   4. Otherwise return None: the library creates a fresh user (suffixing the
    #      username for uniqueness if needed); update_user then creates the link.
    from django.conf import settings
    from allauth.socialaccount.models import SocialAccount
    from allauth.account.models import EmailAddress

    user_id = get_user_id(user)
    if not user_id:
        return None

    # 1. Stable SAML identity link.
    link = (
        SocialAccount.objects.filter(provider=SAML_PROVIDER, uid=user_id)
        .select_related("user")
        .first()
    )
    if link:
        return link.user

    # 2. Verified-email merge, only when this deployment's IdP is trusted.
    email = (user.get("email") or "").lower() if isinstance(user, dict) else ""
    if email and settings.SAML_TRUST_VERIFIED_EMAIL:
        verified = EmailAddress.objects.filter(
            email__iexact=email, verified=True
        ).select_related("user").first()
        if verified:
            SocialAccount.objects.get_or_create(
                provider=SAML_PROVIDER, uid=user_id, defaults={"user": verified.user}
            )
            return verified.user

    # 3. Legacy SAML account created before this link existed (username == uid,
    # no social account). Adopt it and backfill the link.
    try:
        existing = UserModel.objects.get(username__iexact=user_id)
    except UserModel.DoesNotExist:
        existing = None
    if existing and not SocialAccount.objects.filter(user=existing).exists():
        SocialAccount.objects.get_or_create(
            provider=SAML_PROVIDER, uid=user_id, defaults={"user": existing}
        )
        return existing

    # 4. New SAML identity: let the library create a fresh user. update_user
    # (the CREATE_USER trigger) creates the SocialAccount link afterward.
    return None

def generate_token():
        token = "".join(secrets.choice(ascii_letters + digits) for i in range(256))
        # Should realistically never occur, but it's possible.
        while UserIdentityToken.objects.filter(token=token).exists():
            token = "".join(secrets.choice(ascii_letters + digits) for i in range(256))
        return token

def user_token_expires():
    return timezone.now() + timedelta(days=31)

def update_user(user):
    # as of Django_saml2_auth v3.12.0 does not add email address by default
    # to the created use entry in django db according to: 
    # https://github.com/grafana/django-saml2-auth/blob/11b97beaa2a431209e2c54103cb49c033c42ff54/django_saml2_auth/user.py#L93
    # https://github.com/grafana/django-saml2-auth/blob/11b97beaa2a431209e2c54103cb49c033c42ff54/django_saml2_auth/user.py#L165
    # This trigger gets and set the email field in the django user db
    from allauth.socialaccount.models import SocialAccount

    _user = get_user(user)
    if user['email']:
        _user.email = user['email']
        _user.save()
    # Ensure the stable SAML identity link exists (created here for fresh users;
    # saml_get_user backfills legacy ones). Keyed on the assertion uid.
    user_id = get_user_id(user)
    if user_id:
        SocialAccount.objects.get_or_create(
            provider=SAML_PROVIDER, uid=user_id, defaults={"user": _user}
        )
    return _user

class AuthorizedUser(models.Model):
    email = models.EmailField(max_length=254, blank=True)
    username = models.CharField(max_length=128, blank=True)

    def __str__(self):
        return f"{self.email}, {self.username}"

    def clean(self):
        if not self.email and not self.username:
            raise ValidationError("Please enter a value for either email and/or username. Both cannot be empty.")

class IrodAuthorizedUser(models.Model):
    user = models.TextField(max_length=254)
    uid = models.IntegerField()

    def __str__(self):
        return f"{self.user}, {self.uid}"
    
class UserIdentityToken(models.Model):
    user = models.ForeignKey(UserModel, on_delete=models.CASCADE)

    token = models.CharField(max_length=256, unique=True, default=generate_token)
    # Optionally, identify the consumer (probably an app) whom the token was generated for.
    consumer_id = models.CharField(max_length=256, default=None, null=True)
    expires = models.DateTimeField(default=user_token_expires)

    @property
    def valid(self):
        return timezone.now() <= self.expires
    
    @staticmethod
    def compute_app_consumer_id(system_id):
        return f"{ system_id }"

    def __str__(self):
        return f"{ self.user.get_username() }-token-{ self.pk }"
        
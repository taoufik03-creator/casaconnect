from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .forms import (ForgotPasswordForm, PBRAuthenticationForm, ProfileForm, SignUpForm)
from .models import UserProfile

User = get_user_model()

# --- "Mot de passe oublié" settings ---------------------------------------
RESET_SALT = "casaconnect.password-reset"
RESET_SESSION_KEY = "pw_reset_token"
RESET_TOKEN_MAX_AGE = 15 * 60      # seconds the "set a new password" step stays valid
MAX_ATTEMPTS = 5                   # failed identity checks before a temporary lock
LOCK_SECONDS = 15 * 60


class PBRLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PBRAuthenticationForm
    redirect_authenticated_user = True


def signup(request):
    if request.user.is_authenticated:
        return redirect("chat:inbox")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, _("Votre compte a été créé. Bienvenue sur CasaConnect !"))
        return redirect("chat:inbox")
    return render(request, "accounts/signup.html", {"form": form})


# --- Forgot password -------------------------------------------------------
def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


def _failures(key):
    return cache.get(key, 0)


def _register_failure(key):
    cache.add(key, 0, LOCK_SECONDS)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, LOCK_SECONDS)


def _make_token(user):
    # The password-hash fragment makes the token single-use: once the password changes it no longer matches.
    return signing.dumps({"uid": user.pk, "pw": user.password[-16:]}, salt=RESET_SALT)


def _user_from_token(token):
    try:
        data = signing.loads(token, salt=RESET_SALT, max_age=RESET_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=data.get("uid"), is_active=True).first()
    if user and user.password[-16:] == data.get("pw"):
        return user
    return None


def forgot_password(request):
    """Step 1: prove identity with PBR + birth date (no e-mail is stored at sign-up)."""
    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST":
        ip_key = f"pwreset:ip:{_client_ip(request)}"
        pbr = (request.POST.get("PBR") or "").strip().upper().replace(" ", "")
        pbr_key = f"pwreset:pbr:{pbr}"
        if _failures(ip_key) >= MAX_ATTEMPTS or _failures(pbr_key) >= MAX_ATTEMPTS:
            form.add_error(None, _("Trop de tentatives. Réessayez dans 15 minutes ou contactez l'administrateur."))
        elif form.is_valid():
            profile = (UserProfile.objects.select_related("user")
                       .filter(PBR=form.cleaned_data["PBR"], birth_date=form.cleaned_data["birth_date"],
                               user__is_active=True).first())
            if profile:
                cache.delete(ip_key)
                cache.delete(pbr_key)
                request.session[RESET_SESSION_KEY] = _make_token(profile.user)
                return redirect("accounts:reset_password")
            _register_failure(ip_key)
            _register_failure(pbr_key)
            # Same message whether the PBR exists or not: no account enumeration.
            form.add_error(None, _("Les informations saisies ne correspondent à aucun compte."))
    return render(request, "accounts/forgot_password.html", {"form": form})


def reset_password(request):
    """Step 2: choose a new password (only reachable right after a successful step 1)."""
    user = _user_from_token(request.session.get(RESET_SESSION_KEY, ""))
    if user is None:
        request.session.pop(RESET_SESSION_KEY, None)
        messages.error(request, _("Cette étape a expiré. Recommencez la procédure."))
        return redirect("accounts:forgot_password")
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        request.session.pop(RESET_SESSION_KEY, None)
        messages.success(request, _("Mot de passe modifié. Vous pouvez vous connecter."))
        return redirect("accounts:login")
    return render(request, "accounts/reset_password.html", {"form": form})


@login_required
def profile(request):
    profile_obj = getattr(request.user, "profile", None)
    if profile_obj is None:
        messages.error(request, _("Ce compte n'a pas de profil agent (PBR)."))
        return redirect("chat:inbox")
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Profil mis à jour."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form, "profile": profile_obj})

"""Role-based access control. One helper decides who a user is; decorators/mixins guard the views."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

ADMIN = ('admin',)
STAFF = ('admin', 'staff')          # receptionist + owner
CUSTOMER = ('customer',)
MECHANIC = ('mechanic',)

HOME = {'admin': 'dashboard', 'staff': 'dashboard', 'mechanic': 'mech_home', 'customer': 'portal_home'}


def user_role(user):
    """'admin' | 'staff' | 'mechanic' | 'customer' | None (anonymous or no role)."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'admin'
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    if profile.role == 'mechanic' and not profile.mechanic.is_active:
        return None                    # a former employee keeps the record but loses access
    return profile.role


def deny(request, roles):
    """Return a redirect response if the user may not enter, else None."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if user_role(request.user) in roles:
        return None
    messages.error(request, "You don't have access to that page.")
    return redirect('after_login')


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            return deny(request, roles) or view(request, *args, **kwargs)
        return wrapper
    return decorator


class RoleMixin:
    roles = STAFF

    def dispatch(self, request, *args, **kwargs):
        return deny(request, self.roles) or super().dispatch(request, *args, **kwargs)

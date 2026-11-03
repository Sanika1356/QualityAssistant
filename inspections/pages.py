"""Server-rendered pages. Login and role checks happen here, not in the browser."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from .permissions import ADMINISTRATOR, ENGINEER, SUPERVISOR
from .roles import DASHBOARDS, ROLE_KEYS, RoleError, get_role, role_from_key, role_or_none


def role_required(role):
    def decorator(view):
        @wraps(view)
        @ensure_csrf_cookie
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            try:
                user_role = get_role(request.user)
            except RoleError as exc:
                raise PermissionDenied(str(exc))
            if user_role != role:
                raise PermissionDenied(
                    f'This page is for {role}s. You are signed in as {user_role.lower()} '
                    f'{request.user.username}.'
                )
            request.role = user_role
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


PUBLIC_ROLES = [(key, name) for key, name in ROLE_KEYS.items()]


def home(request):
    role = role_or_none(request.user)
    if role:
        return redirect(DASHBOARDS[role])
    return render(request, 'pages/home.html', {'public_roles': PUBLIC_ROLES})


@ensure_csrf_cookie
def login_page(request):
    role = role_or_none(request.user)
    if role:
        return redirect(DASHBOARDS[role])
    chosen = role_from_key(request.GET.get('role'))  # unknown values become None: plain sign-in
    return render(request, 'pages/login.html', {
        'public_roles': PUBLIC_ROLES,
        'chosen_role': chosen,
        'chosen_key': request.GET.get('role', '').strip().lower() if chosen else '',
        'signup_allowed': chosen in (None, ENGINEER),
        'prefill_username': request.GET.get('username', '')[:150],
        'account_created': request.GET.get('created') == '1',
    })


@ensure_csrf_cookie
def signup_page(request):
    role = role_or_none(request.user)
    if role:
        return redirect(DASHBOARDS[role])
    return render(request, 'pages/signup.html', {'public_roles': PUBLIC_ROLES, 'chosen_key': 'engineer'})


@role_required(ADMINISTRATOR)
def admin_panel(request):
    return render(request, 'pages/admin_panel.html')


@role_required(ENGINEER)
def engineer(request):
    return render(request, 'pages/engineer.html')


@role_required(SUPERVISOR)
def supervisor(request):
    return render(request, 'pages/supervisor.html')

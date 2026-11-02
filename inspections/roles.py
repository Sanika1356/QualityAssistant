"""One place that decides a user's role. Every user must be in exactly one role group."""
from .permissions import ADMINISTRATOR, ENGINEER, SUPERVISOR

ROLES = (ADMINISTRATOR, ENGINEER, SUPERVISOR)

# The page each role lands on after signing in.
DASHBOARDS = {
    ADMINISTRATOR: '/admin-panel/',
    ENGINEER: '/engineer/',
    SUPERVISOR: '/supervisor/',
}


class RoleError(Exception):
    """The account cannot be used: it has no role, or more than one."""


def get_role(user):
    """Return the user's single role name, or raise RoleError with a readable reason."""
    if not user.is_authenticated:
        raise RoleError('You are not signed in.')
    roles = sorted(set(user.groups.filter(name__in=ROLES).values_list('name', flat=True)))
    if not roles:
        raise RoleError(
            'Your account has no role yet. Ask an Administrator to make you an '
            'Administrator, Engineer or Supervisor.'
        )
    if len(roles) > 1:
        raise RoleError(
            f'Your account has more than one role ({", ".join(roles)}). '
            'Ask an Administrator to keep only one.'
        )
    return roles[0]


def role_or_none(user):
    try:
        return get_role(user)
    except RoleError:
        return None

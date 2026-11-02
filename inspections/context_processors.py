from .permissions import ADMINISTRATOR, ENGINEER, SUPERVISOR
from .roles import DASHBOARDS, role_or_none

# Header links per role. Add a screen's link here when its page exists.
NAV_LINKS = {
    ADMINISTRATOR: [('Products', DASHBOARDS[ADMINISTRATOR])],
    ENGINEER: [('Inspections', DASHBOARDS[ENGINEER])],
    SUPERVISOR: [('Review', DASHBOARDS[SUPERVISOR])],
}


def current_role(request):
    role = role_or_none(request.user)
    return {
        'current_role': role,
        'dashboard_url': DASHBOARDS.get(role),
        'nav_links': NAV_LINKS.get(role, []),
    }

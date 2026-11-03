from rest_framework.permissions import SAFE_METHODS, BasePermission

ADMINISTRATOR = 'Administrator'
ENGINEER = 'Engineer'
SUPERVISOR = 'Supervisor'


def in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()


class IsEngineer(BasePermission):
    message = 'Only Engineers can submit batches.'

    def has_permission(self, request, view):
        return in_group(request.user, ENGINEER)


class IsEngineerSubmitter(IsEngineer):
    message = 'Only Engineers can submit inspections.'


class IsEngineerOrSupervisor(BasePermission):
    message = 'Only Engineers and Supervisors can view batches.'

    def has_permission(self, request, view):
        return in_group(request.user, ENGINEER) or in_group(request.user, SUPERVISOR)


class HasAnyRole(BasePermission):
    message = 'Only Administrators, Engineers and Supervisors can view model metrics.'

    def has_permission(self, request, view):
        return any(in_group(request.user, role) for role in (ADMINISTRATOR, ENGINEER, SUPERVISOR))


class IsSupervisor(BasePermission):
    message = 'Only Supervisors can review inspections.'

    def has_permission(self, request, view):
        return in_group(request.user, SUPERVISOR)


class IsAdministratorOrReadOnly(BasePermission):
    message = 'Only Administrators can manage products.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user.is_authenticated
        return in_group(request.user, ADMINISTRATOR)


# Round 3: Incident-specific permissions

INCIDENT_ROLES = (ADMINISTRATOR, ENGINEER, SUPERVISOR)


def has_exact_incident_role(user, expected_role):
    if not user.is_authenticated:
        return False

    assigned_roles = set(
        user.groups.filter(name__in=INCIDENT_ROLES)
        .values_list('name', flat=True)
    )

    return len(assigned_roles) == 1 and expected_role in assigned_roles


class IsIncidentEngineer(BasePermission):
    message = 'Only Engineers can create incidents.'

    def has_permission(self, request, view):
        return has_exact_incident_role(request.user, ENGINEER)


class IsIncidentSupervisor(BasePermission):
    message = 'Only Supervisors can review incidents.'

    def has_permission(self, request, view):
        return has_exact_incident_role(request.user, SUPERVISOR)


class CanViewIncidents(BasePermission):
    message = 'Only Engineers and Supervisors can view incidents.'

    def has_permission(self, request, view):
        return (
            has_exact_incident_role(request.user, ENGINEER)
            or has_exact_incident_role(request.user, SUPERVISOR)
        )

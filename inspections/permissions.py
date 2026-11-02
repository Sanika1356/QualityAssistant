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

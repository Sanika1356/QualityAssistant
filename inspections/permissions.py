from rest_framework.permissions import BasePermission

ENGINEER = 'Engineer'
SUPERVISOR = 'Supervisor'


def in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()


class IsEngineer(BasePermission):
    message = 'Only Engineers can submit batches.'

    def has_permission(self, request, view):
        return in_group(request.user, ENGINEER)


class IsEngineerOrSupervisor(BasePermission):
    message = 'Only Engineers and Supervisors can view batches.'

    def has_permission(self, request, view):
        return in_group(request.user, ENGINEER) or in_group(request.user, SUPERVISOR)

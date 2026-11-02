"""Session login API for the browser pages: /api/csrf/, /api/login/, /api/logout/, /api/me/."""
from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .roles import DASHBOARDS, RoleError, get_role


def safe_next(request, role):
    """Follow ?next= only if it stays on this site; otherwise use the role's dashboard."""
    target = request.data.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return DASHBOARDS[role]


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'detail': 'CSRF cookie set.'})


# DRF only checks CSRF for users who are already signed in, so login is protected explicitly.
@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        username = str(request.data.get('username') or '').strip()
        password = str(request.data.get('password') or '')
        if not username or not password:
            return Response(
                {'detail': 'Enter your username and password.'}, status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            # Same message for unknown users and wrong passwords, so accounts can't be guessed.
            return Response(
                {'detail': 'Incorrect username or password.'}, status=status.HTTP_401_UNAUTHORIZED
            )
        try:
            role = get_role(user)
        except RoleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)

        login(request, user)
        return Response({'username': user.username, 'role': role, 'redirect': safe_next(request, role)})


@method_decorator(csrf_protect, name='dispatch')
class LogoutView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({'detail': 'You have signed out.'})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            role = get_role(request.user)
        except RoleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response({'username': request.user.username, 'role': role})

from django.urls import path

from . import pages

# Browser pages. /admin/ stays Django's own admin site.
urlpatterns = [
    path('', pages.home, name='home'),
    path('login/', pages.login_page, name='login'),
    path('admin-panel/', pages.admin_panel, name='admin-panel'),
    path('engineer/', pages.engineer, name='engineer'),
    path('supervisor/', pages.supervisor, name='supervisor'),
]

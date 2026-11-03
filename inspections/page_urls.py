from django.urls import path

from . import pages, sop_views

# Browser pages. /admin/ stays Django's own admin site.
urlpatterns = [
    path('', pages.home, name='home'),
    path('login/', pages.login_page, name='login'),
    path('signup/', pages.signup_page, name='signup'),
    path('admin-panel/', pages.admin_panel, name='admin-panel'),
    path('engineer/', pages.engineer, name='engineer'),
    path('supervisor/', pages.supervisor, name='supervisor'),
    path('sops/<str:document_id>/<str:revision>/', sop_views.sop_pdf, name='sop-pdf'),
]

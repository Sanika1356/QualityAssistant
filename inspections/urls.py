from django.urls import path

from . import auth_api, metrics_api, views

urlpatterns = [
    path('csrf/', auth_api.CsrfView.as_view(), name='api-csrf'),
    path('login/', auth_api.LoginView.as_view(), name='api-login'),
    path('logout/', auth_api.LogoutView.as_view(), name='api-logout'),
    path('signup/', auth_api.SignupView.as_view(), name='api-signup'),
    path('me/', auth_api.MeView.as_view(), name='api-me'),
    path('metrics/', metrics_api.MetricsView.as_view(), name='api-metrics'),
    path('batches/', views.BatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/', views.BatchDetailView.as_view(), name='batch-detail'),
    path('products/', views.ProductListCreateAPIView.as_view(), name='product-list-create'),
    path('inspections/', views.InspectionListAPIView.as_view(), name='inspection-list'),
    path('inspections/<int:pk>/', views.InspectionDetailAPIView.as_view(), name='inspection-detail'),
    path('inspections/<int:pk>/review/', views.InspectionReviewAPIView.as_view(), name='inspection-review'),
    path('inspections/<int:pk>/image/', views.InspectionImageView.as_view(), name='inspection-image'),
]

from django.urls import path

from . import views

urlpatterns = [
    path('batches/', views.BatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/', views.BatchDetailView.as_view(), name='batch-detail'),
]

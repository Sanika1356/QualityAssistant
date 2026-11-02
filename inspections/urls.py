from django.urls import path

from . import views

urlpatterns = [
    path('batches/', views.BatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/', views.BatchDetailView.as_view(), name='batch-detail'),
    # Only the /image/ sub-path, so Person 2's /api/inspections/ and other routes stay free.
    path('inspections/<int:pk>/image/', views.InspectionImageView.as_view(), name='inspection-image'),
]

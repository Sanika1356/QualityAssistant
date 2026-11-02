from django.urls import path

from . import views

urlpatterns = [
    path('batches/', views.BatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/', views.BatchDetailView.as_view(), name='batch-detail'),
    path('products/', views.ProductListCreateAPIView.as_view(), name='product-list-create'),
    path('inspections/', views.InspectionListAPIView.as_view(), name='inspection-list'),
    path('inspections/<int:pk>/', views.InspectionDetailAPIView.as_view(), name='inspection-detail'),
    path('inspections/<int:pk>/review/', views.InspectionReviewAPIView.as_view(), name='inspection-review'),
    path('inspections/<int:pk>/image/', views.InspectionImageView.as_view(), name='inspection-image'),
]

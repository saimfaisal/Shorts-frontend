from django.urls import path

from .views import ShortDetailView, ShortGenerateView, ShortPreviewView

urlpatterns = [
    path("preview/", ShortPreviewView.as_view(), name="short-preview"),
    path("generate/", ShortGenerateView.as_view(), name="short-generate"),
    path("<int:pk>/", ShortDetailView.as_view(), name="short-detail"),
]

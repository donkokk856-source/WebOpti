from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("gallery/", views.gallery, name="gallery"),
    path("settings/", views.settings_view, name="settings"),
    path("serve_file/", views.serve_file, name="serve_file"),
    path("api/run/", views.api_run_pipeline, name="api_run_pipeline"),
    path("api/stop/", views.api_stop_job, name="api_stop_job"),
    path("api/status/", views.api_job_status, name="api_job_status"),
    path("api/save_settings/", views.api_save_settings, name="api_save_settings"),
    path("api/clear_gallery/", views.api_clear_gallery, name="api_clear_gallery"),
]

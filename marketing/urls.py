from django.urls import path
from .views import advertisement_create, advertisement_delete, advertisement_detail, advertisement_list, advertisement_update, announcement_create, announcement_delete, announcement_detail, announcement_list, announcement_update 

urlpatterns = [
    # Advertisement URLs
    path('ads/', advertisement_list, name='advertisement-list'),
    path('ads/create/', advertisement_create, name='advertisement-create'),
    path('ads/<slug:slug>/', advertisement_detail, name='advertisement-detail'),
    path('ads/<slug:slug>/edit/', advertisement_update, name='advertisement-update'),
    path('ads/<slug:slug>/delete/', advertisement_delete, name='advertisement-delete'),

    # Announcement URLs
    path('announcements/', announcement_list, name='announcement-list'),
    path('announcements/create/', announcement_create, name='announcement-create'),
    path('announcements/<slug:slug>/', announcement_detail, name='announcement-detail'),
    path('announcements/<slug:slug>/edit/', announcement_update, name='announcement-update'),
    path('announcements/<slug:slug>/delete/', announcement_delete, name='announcement-delete'),
]
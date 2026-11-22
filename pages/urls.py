from django.urls import path
from . import seo, views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("sitemap.xml", seo.sitemap_xml, name="sitemap"),
    path("robots.txt", seo.robots_txt, name="robots"),
    path("health/", views.health, name="health"),
    path("<slug:slug>/", views.info_page, name="info"),
]
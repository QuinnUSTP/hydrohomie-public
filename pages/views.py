from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from . import schema
from .content import HOME_DESCRIPTION, HOME_OG_TITLE, PAGES_BY_SLUG, RELATED


class HomeView(TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["intro"] = schema.home_intro()
        context["json_ld"] = schema.dumps(schema.home_graph())
        context["og_title"] = HOME_OG_TITLE
        context["og_description"] = HOME_DESCRIPTION
        return context


def info_page(request, slug):
    page = PAGES_BY_SLUG.get(slug)
    if page is None:
        raise Http404
    related = [PAGES_BY_SLUG[s] for s in RELATED.get(slug, [])]
    return render(request, "pages/info.html", {
        "page": page,
        "related": related,
        "og_title": page["title"],
        "og_description": page["description"],
    })

def health(request):
    response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response
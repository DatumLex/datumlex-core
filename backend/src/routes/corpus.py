from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from src.accounts.middleware import denied
from src.db.models import LegalCorpusItem
from src.routes.statistics import endpoint
from src.services.corpus_publication import court_items, published_items, reviewer
from src.services.research import source_item
from src.services.corpus_catalog import inventory

@endpoint
def catalog(request):
    return inventory(request.GET)


@require_GET
def detail(request, source_id):
    item = get_object_or_404(court_items(request.user, published_items()), pk=source_id)
    return JsonResponse(source_item(item, max_excerpt=None))


@require_GET
def review_queue(request):
    if not reviewer(request.user):
        return denied("Acesso restrito à revisão jurídica.")
    rows = court_items(request.user, LegalCorpusItem.objects.exclude(review_status="approved"))
    return JsonResponse({"items": list(rows.order_by("pk").values("id", "title", "category", "court", "review_status")[:50])})


@require_GET
def review_detail(request, source_id):
    if not reviewer(request.user):
        return denied("Acesso restrito à revisão jurídica.")
    item = get_object_or_404(court_items(request.user, LegalCorpusItem.objects.all()), pk=source_id)
    return JsonResponse({**source_item(item), "origin_key": item.origin_key, "provenance": item.provenance})

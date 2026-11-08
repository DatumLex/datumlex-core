from src.routes.statistics import endpoint
from src.services.corpus_catalog import inventory

@endpoint
def catalog(request):
    return inventory(request.GET)

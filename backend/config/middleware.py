from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class LocalCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        response = HttpResponse(status=204) if request.method == "OPTIONS" else self.get_response(request)
        origin = request.headers.get("Origin")
        if origin in settings.CORS_ALLOWED_ORIGINS:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
        patch_vary_headers(response, ["Origin"])
        return response

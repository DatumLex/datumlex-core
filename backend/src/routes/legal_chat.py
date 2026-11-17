import json

from django.http import HttpResponse, JsonResponse
from src.routes.nlp_dashboard import endpoint
from src.services import legal_chat as service


@endpoint(['POST'])
def generate(request, snapshot_id):
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or set(payload) - {'question', 'consent', 'parent_id'}:
            raise ValueError('invalid_body')
        draft = service.generate(request.user, snapshot_id, payload.get('question'), payload.get('consent'), payload.get('parent_id'))
        return service.serialize(draft)
    except ValueError as exc:
        return JsonResponse({'error': {'message': str(exc)}}, status=400)
    except service.ChatUnavailable as exc:
        return JsonResponse({'error': {'message': str(exc)}}, status=503)


@endpoint(['GET', 'POST'])
def detail(request, draft_id):
    if request.method == 'POST':
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or set(payload) != {'expected_sha256', 'conclusions', 'confirmed'}:
            raise ValueError('invalid_approval')
        draft = service.approve(request.user, draft_id, payload['expected_sha256'], payload['conclusions'], payload['confirmed'])
    else:
        draft = service.read(request.user, draft_id)
    return service.serialize(draft)


@endpoint(['GET'])
def export(request, draft_id):
    draft = service.read(request.user, draft_id)
    if draft.status != 'approved':
        return JsonResponse({'error': {'message': 'Aprovação humana obrigatória antes de exportar.'}}, status=409)
    content = json.dumps(service.serialize(draft), ensure_ascii=False, indent=2)
    response = HttpResponse(content, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="datumlex-analise-{draft.pk}.json"'
    return response

from django.db import transaction
from .views import api
from .models import AuditEvent
from src.services import server_automation as service


def authorize(request):
    if request.user.role != 'Master':
        raise PermissionError('Somente o perfil Master pode configurar a automação desta instalação.')


@api(['GET', 'PUT'])
@transaction.atomic
def settings(request):
    authorize(request)
    if request.method == 'PUT':
        service.save(request.payload, request.user)
        AuditEvent.objects.create(actor=request.user, actor_name=request.user.name, action='automation.configured')
    return service.status()


@api(['POST'])
@transaction.atomic
def actions(request):
    authorize(request)
    if set(request.payload) != {'action'}:
        raise ValueError('Ação inválida.')
    service.action(request.payload['action'], request.user)
    AuditEvent.objects.create(actor=request.user, actor_name=request.user.name,
                              action='automation.' + request.payload['action'])
    return service.status()

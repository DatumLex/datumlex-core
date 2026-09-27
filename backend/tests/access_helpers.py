from src.accounts.models import Court, User


def authorize_data(client):
    user = User.objects.create_user(username="analyst", name="Test Analyst", approved=True)
    court, _ = Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})
    user.courts.add(court)
    client.force_login(user)

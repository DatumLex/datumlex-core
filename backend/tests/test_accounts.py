from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase

from src.accounts.models import AuditEvent, Court, User
from src.accounts.provisioning import provision_support


class AccessTests(TestCase):
    def setUp(self):
        self.court = Court.objects.create(code="TJDFT", name="TJDFT")
        self.master = User.objects.create_user(
            username="master",
            name="Test Master",
            email="master@example.com",
            cpf="12345678909",
            password="abcdefgh",
            role="Master",
            approved=True,
        )
        self.admin = User.objects.create_user(
            username="admin", name="Test Admin", password="abcdefgh", role="Admin", approved=True
        )
        self.standard = User.objects.create_user(
            username="standard",
            name="Test Standard",
            email="standard@example.com",
            cpf="39053344705",
            password="abcdefgh",
            approved=True,
        )
        self.pending = User.objects.create_user(
            username="pending",
            name="Test Pending",
            email="pending@example.com",
            cpf="52998224725",
            password="abcdefgh",
        )
        self.support = provision_support("fixed@")
        self.payload = {
            "name": "Pessoa Teste",
            "cpf": "111.444.777-35",
            "email": "test@example.com",
            "password": "abcdefgh",
        }

    def send(self, path, data=None, method="post", client=None):
        return getattr(client or self.client, method)(
            "/api/" + path + "/", data=data or {}, content_type="application/json"
        )

    def test_register_pending_hash_and_no_privilege_assignment(self):
        result = self.send("auth/register", self.payload)
        self.assertEqual(result.status_code, 200)
        user = User.objects.get(email="test@example.com")
        self.assertEqual(user.role, "Padrão")
        self.assertFalse(user.approved)
        self.assertFalse(user.must_change_password)
        self.assertFalse(user.courts.exists())
        self.assertNotEqual(user.password, "abcdefgh")
        self.assertTrue(user.check_password("abcdefgh"))
        self.assertEqual(
            self.send("auth/login", {"login": user.email, "password": "abcdefgh"}).status_code, 403
        )
        self.assertEqual(self.send("auth/register", {**self.payload, "role": "Master"}).status_code, 400)

    def test_identity_validation_and_database_uniqueness(self):
        for change in (
            {"cpf": "11111111111"},
            {"cpf": "12345678900"},
            {"email": "bad"},
            {"password": "short"},
            {"name": "Single"},
            {"password": []},
        ):
            self.assertEqual(self.send("auth/register", {**self.payload, **change}).status_code, 400)
        self.assertEqual(self.send("auth/register", self.payload).status_code, 200)
        self.assertEqual(
            self.send("auth/register", {**self.payload, "email": "TEST@EXAMPLE.COM"}).status_code, 409
        )

    def test_email_cpf_login_and_session_logout(self):
        self.pending.approved = True
        self.pending.save()
        for identifier in ("PENDING@example.com", "529.982.247-25"):
            self.assertEqual(
                self.send("auth/login", {"login": identifier, "password": "abcdefgh"}).status_code, 200
            )
            self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
            self.assertEqual(self.send("auth/logout").status_code, 200)
            self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        # Generated/ordinary usernames must never become a third public login mode.
        self.assertEqual(
            self.send("auth/login", {"login": "master", "password": "abcdefgh"}).status_code, 403
        )

    def test_all_analytics_require_approval_and_court_authorization(self):
        for route in ("scope", "statistics", "distribution", "instances", "processes"):
            self.assertEqual(self.client.get(f"/api/{route}/").status_code, 401)
        self.client.force_login(self.pending)
        self.assertEqual(self.client.get("/api/scope/").status_code, 403)
        self.client.force_login(self.master)
        self.assertEqual(self.client.get("/api/statistics/").status_code, 403)
        self.master.courts.add(self.court)
        for route in ("scope", "statistics", "distribution", "instances", "processes"):
            self.assertEqual(self.client.get(f"/api/{route}/").status_code, 200)
            self.assertEqual(self.client.get(f"/api/{route}/?court=TJSP").status_code, 403)
        self.master.courts.clear()
        self.assertEqual(self.client.get("/api/statistics/").status_code, 403)

    def test_standard_cannot_manage_or_read_audit(self):
        self.client.force_login(self.standard)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        self.assertEqual(self.send("users", self.payload).status_code, 403)
        self.assertEqual(self.send(f"users/{self.admin.pk}", {"role": "Master"}, "patch").status_code, 403)
        self.assertEqual(self.client.get("/api/audit/").status_code, 403)

    def test_admin_cannot_escalate_edit_privileged_or_delete(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/users/").status_code, 200)
        for role in ("Master", "Admin"):
            self.assertEqual(self.send("users", {**self.payload, "role": role}).status_code, 403)
            self.assertEqual(self.send(f"users/{self.standard.pk}", {"role": role}, "patch").status_code, 403)
        for user in (self.master, self.admin, self.support):
            self.assertEqual(self.send(f"users/{user.pk}", {"status": "Ativo"}, "patch").status_code, 403)
        self.assertEqual(self.send(f"users/{self.standard.pk}", method="delete").status_code, 403)
        self.assertEqual(self.send("users", {**self.payload, "support": True}).status_code, 400)

    def test_admin_approval_is_persisted_and_audited(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.send(
                f"users/{self.pending.pk}", {"status": "Ativo", "courts": ["TJDFT"]}, "patch"
            ).status_code,
            200,
        )
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.approved)
        self.assertTrue(self.pending.courts.filter(code="TJDFT").exists())
        self.assertTrue(
            AuditEvent.objects.filter(
                action="user.updated", actor=self.admin, target_id=self.pending.pk
            ).exists()
        )
        self.client.force_login(self.pending)
        self.assertEqual(self.client.get("/api/statistics/").status_code, 200)

    def test_support_hidden_immutable_password_and_dynamic_courts(self):
        self.client.force_login(self.master)
        for query in ("", "?q=suport", "?role=Master", "?pending=true"):
            self.assertNotIn(
                self.support.pk, [u["id"] for u in self.client.get("/api/users/" + query).json()["users"]]
            )
        for payload in (
            {"role": "Padrão"},
            {"status": "Inativo"},
            {"password": "replacement"},
            {"support": False},
            {"courts": []},
        ):
            self.assertEqual(self.send(f"users/{self.support.pk}", payload, "patch").status_code, 403)
        self.assertEqual(self.send(f"users/{self.support.pk}", method="delete").status_code, 403)
        self.send("auth/logout")
        self.assertEqual(self.send("auth/login", {"login": "suport", "password": "fixed@"}).status_code, 200)
        self.assertEqual(
            self.send("auth/password", {"current_password": "fixed@", "password": "abcdefgh"}).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/statistics/").status_code, 200)
        Court.objects.create(code="STJ", name="STJ")
        data = self.client.get("/api/auth/me/").json()["user"]
        self.assertIn("STJ", data["courts"])
        self.assertFalse(data["must_change_password"])
        self.assertTrue(AuditEvent.objects.filter(actor=self.support, action="support.request").exists())
        self.assertEqual(provision_support("different").password, self.support.password)

    def test_support_protection_in_model_bulk_update_and_delete(self):
        self.support.set_password("replacement")
        with self.assertRaises(ValidationError):
            self.support.save()
        for update in (
            {"password": "replacement"},
            {"role": "Admin"},
            {"is_active": False},
            {"support": False, "username": "renamed"},
        ):
            with self.assertRaises(DatabaseError), transaction.atomic():
                User.objects.filter(pk=self.support.pk).update(**update)
        with self.assertRaises(ProtectedError):
            User.objects.filter(pk=self.support.pk).delete()

    def test_master_create_change_profile_delete_and_session_revocation(self):
        self.client.force_login(self.master)
        result = self.send("users", {**self.payload, "role": "Admin", "status": "Ativo", "courts": ["TJDFT"]})
        self.assertEqual(result.status_code, 200)
        pk = result.json()["user"]["id"]
        self.assertTrue(result.json()["user"]["must_change_password"])
        self.assertEqual(self.send(f"users/{pk}", {"role": "Master"}, "patch").status_code, 200)
        other = Client()
        other.force_login(User.objects.get(pk=pk))
        self.assertEqual(self.send(f"users/{pk}", {"status": "Inativo"}, "patch").status_code, 200)
        self.assertEqual(other.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.send(f"users/{pk}", method="delete").status_code, 200)
        self.assertEqual(self.send(f"users/{self.master.pk}", {"role": "Padrão"}, "patch").status_code, 403)

    def test_master_can_reset_password_without_disclosing_it(self):
        other = Client()
        other.force_login(self.standard)
        self.client.force_login(self.master)
        payload = {"password": "new-manual-password", "password_confirmation": "new-manual-password"}
        response = self.send(f"users/{self.standard.pk}", payload, "patch")
        self.assertEqual(response.status_code, 200)
        self.standard.refresh_from_db()
        self.assertTrue(self.standard.check_password(payload["password"]))
        self.assertTrue(self.standard.must_change_password)
        self.assertFalse(self.standard.check_password("abcdefgh"))
        self.assertEqual(other.get("/api/auth/me/").status_code, 401)
        self.assertNotIn(payload["password"], response.content.decode())
        event = AuditEvent.objects.get(action="password.reset_by_master")
        self.assertEqual(event.actor_id, self.master.pk)
        self.assertEqual(event.target_id, self.standard.pk)
        self.assertNotIn(payload["password"], str(event.details))
        other.force_login(self.standard)
        self.assertEqual(other.get("/api/statistics/").status_code, 403)
        changed = self.send(
            "auth/password",
            {"current_password": payload["password"], "password": "personal-new-password"},
            client=other,
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json()["user"]["must_change_password"])

    def test_management_creation_password_change_option(self):
        for actor in (self.master, self.admin):
            self.client.force_login(actor)
            for value in (True, False):
                result = self.send("users", {**self.payload, "must_change_password": value})
                self.assertEqual(result.status_code, 200)
                user = User.objects.get(pk=result.json()["user"]["id"])
                self.assertEqual(user.must_change_password, value)
                user.delete()
            result = self.send("users", {**self.payload, "must_change_password": "false"})
            self.assertEqual(result.status_code, 400)
        self.client.logout()
        self.assertEqual(
            self.send("auth/register", {**self.payload, "must_change_password": False}).status_code, 400
        )

    def test_manual_password_requires_master_confirmation_and_minimum(self):
        payload = {"password": "newpassword", "password_confirmation": "newpassword"}
        self.client.force_login(self.admin)
        self.assertEqual(self.send(f"users/{self.standard.pk}", payload, "patch").status_code, 403)
        self.client.force_login(self.master)
        for invalid in (
            {"password": "newpassword"},
            {"password": "newpassword", "password_confirmation": "different"},
            {"password": "short", "password_confirmation": "short"},
            {"password_confirmation": "newpassword"},
        ):
            self.assertEqual(self.send(f"users/{self.standard.pk}", invalid, "patch").status_code, 400)
        self.standard.refresh_from_db()
        self.assertTrue(self.standard.check_password("abcdefgh"))
        self.assertEqual(self.send(f"users/{self.support.pk}", payload, "patch").status_code, 403)
        self.assertEqual(self.send(f"users/{self.master.pk}", payload, "patch").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_initial_password_change_for_regular_accounts(self):
        self.standard.must_change_password = True
        self.standard.save()
        self.client.force_login(self.standard)
        self.assertEqual(self.client.get("/api/statistics/").status_code, 403)
        other = Client()
        other.force_login(self.standard)
        result = self.send("auth/password", {"current_password": "abcdefgh", "password": "newpassword"})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["user"]["must_change_password"])
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.assertEqual(other.get("/api/auth/me/").status_code, 401)

    def test_csrf_is_required_and_origin_checked(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.send("auth/login", {}, client=client).status_code, 403)
        token = client.get("/api/auth/csrf/").json()["csrfToken"]
        result = client.post(
            "/api/auth/login/",
            {"login": "master@example.com", "password": "abcdefgh"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(result.status_code, 200)
        token = result.json()["csrfToken"]
        self.assertEqual(
            client.post(
                "/api/auth/logout/",
                {},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
                HTTP_ORIGIN="https://evil.example",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                "/api/auth/logout/", {}, content_type="application/json", HTTP_X_CSRFTOKEN=token
            ).status_code,
            200,
        )

    def test_rate_limit_and_audit_exclude_secrets(self):
        for _ in range(30):
            self.send("auth/login", {"login": "unknown@example.com", "password": "secret-attempt"})
        response = self.send("auth/login", {"login": "unknown@example.com", "password": "secret-attempt"})
        self.assertContains(response, "15 minutos", status_code=403)
        self.assertNotIn("secret-attempt", str(list(AuditEvent.objects.values())))

    def test_invalid_court_unknown_fields_filters_and_deleted_account(self):
        self.client.force_login(self.master)
        self.assertEqual(self.send("users", {**self.payload, "courts": ["FAKE"]}).status_code, 400)
        self.assertEqual(self.send("users", {**self.payload, "is_superuser": True}).status_code, 400)
        self.assertEqual(self.send("users/999999", {"role": "Admin"}, "patch").status_code, 404)
        response = self.client.get("/api/users/?pending=true&role=Padrão&q=Pending").json()
        self.assertEqual([u["id"] for u in response["users"]], [self.pending.pk])

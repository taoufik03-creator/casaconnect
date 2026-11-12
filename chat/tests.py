from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from chat.models import Conversation, Membership, Message
from chat.services import dispatch_due_messages

User = get_user_model()


def make_user(pbr, first="A", last="B", pw="Str0ng-pass-123"):
    u = User.objects.create_user(username=pbr, password=pw, first_name=first, last_name=last)
    UserProfile.objects.create(user=u, PBR=pbr, birth_date=date(1990, 5, 17))
    return u


class BaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.c = make_user("P001", "Amal", "Alaoui"), make_user("P002", "Bilal", "Benani"), make_user("P003", "Chaima", "Cherkaoui")
        self.client.login(username="P001", password="Str0ng-pass-123")

    def send(self, to, body="Bonjour", **extra):
        return self.client.post(reverse("chat:compose"), {"recipients": [u.pk for u in to], "body": body,
                                                           "action": "send", **extra})


class MessagingTests(BaseCase):
    def test_single_recipient_makes_direct_conversation_and_reuses_it(self):
        self.send([self.b]); self.send([self.b], "Encore")
        self.assertEqual(Conversation.objects.count(), 1)
        conv = Conversation.objects.get()
        self.assertFalse(conv.is_group)
        self.assertEqual(conv.messages.filter(status="sent").count(), 2)

    def test_multiple_recipients_auto_create_group(self):
        self.send([self.b, self.c])
        conv = Conversation.objects.get()
        self.assertTrue(conv.is_group)
        self.assertEqual(set(conv.members.all()), {self.a, self.b, self.c})
        self.send([self.c, self.b], "Re")           # same members -> same group
        self.assertEqual(Conversation.objects.count(), 1)

    def test_no_access_to_foreign_conversation(self):
        self.send([self.b])
        conv = Conversation.objects.get()
        self.client.logout(); self.client.login(username="P003", password="Str0ng-pass-123")
        self.assertEqual(self.client.get(reverse("chat:conversation", args=[conv.pk])).status_code, 404)

    def test_unread_and_inbox(self):
        self.send([self.b])
        self.client.logout(); self.client.login(username="P002", password="Str0ng-pass-123")
        r = self.client.get(reverse("chat:inbox"))
        self.assertEqual(r.context["rows"][0].unread, 1)
        self.assertEqual(r.context["unread_total"], 1)
        conv = Conversation.objects.get()
        self.client.get(reverse("chat:conversation", args=[conv.pk]))
        self.assertEqual(self.client.get(reverse("chat:inbox")).context["rows"][0].unread, 0)

    def test_stars(self):
        self.send([self.b])
        conv, msg = Conversation.objects.get(), Message.objects.get()
        self.client.post(reverse("chat:star_message", args=[msg.pk]))
        self.client.post(reverse("chat:star_conversation", args=[conv.pk]))
        self.assertTrue(msg.starred_by.filter(pk=self.a.pk).exists())
        self.assertTrue(Membership.objects.get(conversation=conv, user=self.a).is_starred)
        self.assertFalse(Membership.objects.get(conversation=conv, user=self.b).is_starred)  # per-user
        self.assertContains(self.client.get(reverse("chat:starred")), "Bonjour")
        r = self.client.post(reverse("chat:star_message", args=[msg.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.json(), {"starred": False})


class ScheduleAndDraftTests(BaseCase):
    def test_schedule_then_dispatch(self):
        when = (timezone.localtime() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("chat:compose"), {"recipients": [self.b.pk, self.c.pk], "body": "Plus tard",
                                                    "action": "schedule", "scheduled_for": when})
        msg = Message.objects.get()
        self.assertEqual(msg.status, "scheduled")
        self.assertEqual(Conversation.objects.count(), 0)          # group is created at send time
        self.assertContains(self.client.get(reverse("chat:scheduled")), "Plus tard")
        self.assertEqual(dispatch_due_messages(), 0)
        Message.objects.update(scheduled_for=timezone.now() - timedelta(minutes=1))
        self.assertEqual(dispatch_due_messages(), 1)
        self.assertEqual(dispatch_due_messages(), 0)               # not sent twice
        msg.refresh_from_db()
        self.assertEqual(msg.status, "sent")
        self.assertTrue(Conversation.objects.get().is_group)

    def test_schedule_in_past_rejected(self):
        past = (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("chat:compose"), {"recipients": [self.b.pk], "body": "x",
                                                        "action": "schedule", "scheduled_for": past})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)

    def test_unschedule_moves_back_to_drafts(self):
        when = (timezone.localtime() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("chat:compose"), {"recipients": [self.b.pk], "body": "x", "action": "schedule",
                                                    "scheduled_for": when})
        msg = Message.objects.get()
        self.client.post(reverse("chat:unschedule", args=[msg.pk]))
        msg.refresh_from_db()
        self.assertEqual((msg.status, msg.scheduled_for), ("draft", None))

    def test_autosave_creates_updates_and_deletes_draft(self):
        url = reverse("chat:draft_autosave")
        d = self.client.post(url, {"body": "brou", "recipients": [self.b.pk]}).json()["draft_id"]
        self.assertEqual(Message.objects.filter(status="draft").count(), 1)
        self.client.post(url, {"body": "brouillon", "recipients": [self.b.pk], "draft_id": d})
        self.assertEqual(Message.objects.get(pk=d).body, "brouillon")
        self.assertEqual(Message.objects.count(), 1)
        self.assertContains(self.client.get(reverse("chat:drafts")), "brouillon")
        self.client.post(url, {"body": "", "draft_id": d})
        self.assertEqual(Message.objects.count(), 0)

    def test_sending_a_draft_converts_it(self):
        url = reverse("chat:draft_autosave")
        d = self.client.post(url, {"body": "hello", "recipients": [self.b.pk]}).json()["draft_id"]
        self.send([self.b], "hello", draft_id=d)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Message.objects.get().status, "sent")

    def test_conversation_reply_draft_is_reused(self):
        self.send([self.b])
        conv = Conversation.objects.get()
        url = reverse("chat:draft_autosave")
        self.client.post(url, {"body": "a", "conversation_id": conv.pk})
        self.client.post(url, {"body": "ab", "conversation_id": conv.pk})
        self.assertEqual(Message.objects.filter(status="draft").count(), 1)
        self.assertContains(self.client.get(reverse("chat:conversation", args=[conv.pk])), "ab</textarea>")


class AccountTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_signup_creates_user_and_profile(self):
        r = self.client.post(reverse("accounts:signup"), {
            "PBR": "x123", "first_name": "Taoufik", "last_name": "Test", "birth_date": "2000-01-15",
            "password1": "Zq9!longpass", "password2": "Zq9!longpass"})
        self.assertRedirects(r, reverse("chat:inbox"))
        p = UserProfile.objects.get(PBR="X123")
        self.assertEqual(p.user.username, "X123")
        self.assertTrue(p.user.check_password("Zq9!longpass"))

    def test_signup_rejects_duplicate_pbr_and_bad_password(self):
        make_user("DUP1")
        r = self.client.post(reverse("accounts:signup"), {
            "PBR": "dup1", "first_name": "a", "last_name": "b", "birth_date": "2000-01-15",
            "password1": "12345678", "password2": "12345678"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_login_with_pbr_case_insensitive(self):
        make_user("LOG1")
        self.assertTrue(self.client.login(username="LOG1", password="Str0ng-pass-123"))
        r = self.client.post(reverse("accounts:login"), {"username": "log1", "password": "Str0ng-pass-123"})
        self.assertRedirects(r, reverse("chat:inbox"))

    def test_forgot_password_flow(self):
        u = make_user("RST1")
        old_hash = u.password
        r = self.client.post(reverse("accounts:forgot_password"), {"PBR": "rst1", "birth_date": "1990-05-17"})
        self.assertRedirects(r, reverse("accounts:reset_password"))
        r = self.client.post(reverse("accounts:reset_password"), {"new_password1": "N3w-secret-pw!", "new_password2": "N3w-secret-pw!"})
        self.assertRedirects(r, reverse("accounts:login"))
        u.refresh_from_db()
        self.assertNotEqual(u.password, old_hash)
        self.assertTrue(u.check_password("N3w-secret-pw!"))
        # step 2 is no longer reachable
        self.assertRedirects(self.client.get(reverse("accounts:reset_password")), reverse("accounts:forgot_password"))

    def test_forgot_password_wrong_birthdate_and_lockout(self):
        make_user("RST2")
        for _ in range(5):
            r = self.client.post(reverse("accounts:forgot_password"), {"PBR": "RST2", "birth_date": "1991-01-01"})
            self.assertContains(r, "ne correspondent")
        # even the right date is refused while locked
        r = self.client.post(reverse("accounts:forgot_password"), {"PBR": "RST2", "birth_date": "1990-05-17"})
        self.assertContains(r, "Trop de tentatives")

    def test_reset_requires_step_one(self):
        self.assertRedirects(self.client.get(reverse("accounts:reset_password")), reverse("accounts:forgot_password"))

    def test_avatar_upload(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image
        import tempfile
        make_user("AV01")
        self.client.login(username="AV01", password="Str0ng-pass-123")
        buf = io.BytesIO(); Image.new("RGB", (20, 20), "red").save(buf, "PNG")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            r = self.client.post(reverse("accounts:profile"), {
                "first_name": "A", "last_name": "B", "avatar": SimpleUploadedFile("me.png", buf.getvalue(), "image/png")})
            self.assertRedirects(r, reverse("accounts:profile"))
            self.assertTrue(UserProfile.objects.get(PBR="AV01").avatar.name.startswith("avatars/"))


class LanguageTests(BaseCase):
    def switch(self, code):
        return self.client.post(reverse("set_language"), {"language": code, "next": "/"})

    def test_default_is_french_ltr(self):
        r = self.client.get(reverse("chat:inbox"))
        self.assertContains(r, 'lang="fr" dir="ltr"')
        self.assertContains(r, "Boîte de réception")

    def test_switch_to_arabic_gives_rtl_and_translations(self):
        self.switch("ar")
        r = self.client.get(reverse("chat:inbox"))
        self.assertContains(r, 'lang="ar" dir="rtl"')
        self.assertContains(r, "صندوق الوارد")
        self.assertNotContains(r, "Boîte de réception")
        self.switch("fr")
        self.assertContains(self.client.get(reverse("chat:inbox")), 'dir="ltr"')

    def test_every_page_renders_in_arabic(self):
        self.send([self.b, self.c])
        conv = Conversation.objects.get()
        self.switch("ar")
        for url in [reverse("chat:inbox"), reverse("chat:compose"), reverse("chat:drafts"), reverse("chat:scheduled"),
                    reverse("chat:starred"), reverse("chat:conversation", args=[conv.pk]), reverse("accounts:profile")]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'dir="rtl"')
        self.assertContains(self.client.get(reverse("chat:compose")), "جارٍ الحفظ")      # JS status texts
        self.assertContains(self.client.get(reverse("chat:conversation", args=[conv.pk])), "أعضاء")  # blocktrans

    def test_auth_pages_arabic_and_messages(self):
        self.client.logout()
        self.switch("ar")
        self.assertContains(self.client.get(reverse("accounts:login")), "تسجيل الدخول")
        self.assertContains(self.client.get(reverse("accounts:signup")), "تاريخ الميلاد")
        r = self.client.post(reverse("accounts:forgot_password"), {"PBR": "NOPE", "birth_date": "1990-01-01"})
        self.assertContains(r, "المعلومات المدخلة لا تطابق أي حساب")

    def test_flash_message_translated(self):
        self.switch("ar")
        r = self.client.post(reverse("chat:compose"), {"recipients": [self.b.pk], "body": "x", "action": "draft"}, follow=True)
        self.assertContains(r, "تم حفظ المسودة")

    def test_language_switch_available_on_every_layout(self):
        self.assertContains(self.client.get(reverse("chat:inbox")), "العربية")
        self.client.logout()
        self.assertContains(self.client.get(reverse("accounts:login")), "Français")

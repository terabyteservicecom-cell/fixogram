import json
import os
from datetime import timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from talent.catalog import seed_catalog
from talent.models import Banner, BlogCategory, Category, IdentityDocument, JobPost, LoginCode, Message, PhoneRequest, Post, PostComment, Presence, ProfileRole, PushSubscription, Rating, Role, SmsSetting, StaffLog, Thread, ViolationReport, WelcomeMessage
from talent.sms import SmsError, deliver_code


class CastingPlatformTests(TestCase):
    def setUp(self):
        seed_catalog()
        self.actor = User.objects.create_user("actor1", password="pass12345")
        self.actor.profile.display_name = "نگار"
        self.actor.profile.phone = "09120000000"
        self.actor.profile.city = "تهران"
        self.actor.profile.listed_until = timezone.now() + timedelta(days=365)
        self.actor.profile.save()
        self.seeker = User.objects.create_user("seeker1", password="pass12345")
        self.seeker.profile.display_name = "تهیه‌کننده"
        self.seeker.profile.phone = "09121111111"
        self.seeker.profile.save()
        self.outsider = User.objects.create_user("outsider", password="pass12345")
        role = Role.objects.get(slug="laptop-repair")
        ProfileRole.objects.create(
            profile=self.actor.profile,
            role=role,
            status=ProfileRole.Status.APPROVED,
        )

    def test_phone_stays_hidden_until_manager_approves(self):
        self.actor.profile.contact_phone = "02188776655"
        self.actor.profile.save(update_fields=["contact_phone"])
        self.client.login(username="seeker1", password="pass12345")
        url = reverse("profile", args=[self.actor.profile.pk])
        response = self.client.get(url)
        self.assertNotContains(response, "09120000000")
        self.assertNotContains(response, "02188776655")
        self.assertContains(response, "درخواست دیدن شماره")
        self.assertContains(response, "متخصص در تعمیرات")
        self.assertContains(response, "report-box")
        self.assertContains(response, "report-link")
        self.assertContains(response, "گزارش تخلف")

        self.client.post(reverse("request_phone", args=[self.actor.profile.pk]))
        request = PhoneRequest.objects.get()
        self.assertEqual(request.status, PhoneRequest.Status.PENDING)
        response = self.client.get(url)
        self.assertNotContains(response, "09120000000")
        self.assertNotContains(response, "02188776655")

        request.status = PhoneRequest.Status.APPROVED
        request.save()
        response = self.client.get(url)
        self.assertContains(response, "02188776655")
        self.assertNotContains(response, "09120000000")

    def test_owner_sees_own_phone_and_cannot_rate_self(self):
        self.actor.profile.contact_phone = "02188776655"
        self.actor.profile.save(update_fields=["contact_phone"])
        self.client.login(username="actor1", password="pass12345")
        response = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(response, "02188776655")
        self.assertNotContains(response, "09120000000")
        self.client.post(reverse("rate", args=[self.actor.profile.pk]), {"score": 5})
        self.assertEqual(Rating.objects.count(), 0)

    def test_search_by_province(self):
        response = self.client.get(reverse("home"), {"city": "تهران"})
        self.assertContains(response, "نگار")
        self.assertContains(response, "اصفهان")
        response = self.client.get(reverse("home"), {"city": "اصفهان"})
        self.assertNotContains(response, "نگار")

    def test_search_by_approved_role(self):
        pending = User.objects.create_user("pending1", password="pass12345")
        pending.profile.display_name = "رضا"
        pending.profile.save()
        ProfileRole.objects.create(
            profile=pending.profile,
            role=Role.objects.get(slug="printer"),
            status=ProfileRole.Status.PENDING,
        )
        response = self.client.get(reverse("home"), {"role": Role.objects.get(slug="laptop-repair").pk})
        self.assertContains(response, "نگار")
        self.assertContains(response, "1 مورد پیدا شد")
        self.assertNotContains(response, "<strong>رضا</strong>")
        response = self.client.get(reverse("home"), {"role": Role.objects.get(slug="printer").pk})
        self.assertContains(response, "0 مورد پیدا شد")
        self.assertNotContains(response, "<strong>رضا</strong>")

    def test_messages_are_private(self):
        self.client.login(username="seeker1", password="pass12345")
        thread = Thread.between(self.seeker, self.actor)
        self.client.post(reverse("thread", args=[thread.pk]), {"body": "فردا سر صحنه"})
        self.assertEqual(Message.objects.get().body, "فردا سر صحنه")
        self.assertEqual(Message.objects.get().status, "pending")
        self.assertContains(self.client.get(reverse("thread", args=[thread.pk])), "در انتظار تایید")
        self.client.logout()
        self.client.login(username="actor1", password="pass12345")
        self.assertNotContains(self.client.get(reverse("inbox")), "فردا سر صحنه")
        self.client.logout()
        self.client.login(username="outsider", password="pass12345")
        response = self.client.get(reverse("thread", args=[thread.pk]))
        self.assertRedirects(response, reverse("inbox"))
        self.assertNotContains(self.client.get(reverse("inbox")), "فردا سر صحنه")

    def test_recipient_is_told_when_a_message_is_approved(self):
        thread = Thread.between(self.seeker, self.actor)
        Message.objects.create(thread=thread, sender=self.seeker, body="فردا می‌آیم", status="pending")
        self.client.login(username="actor1", password="pass12345")
        quiet = self.client.get(reverse("message_ping"))
        self.assertEqual(quiet.json()["count"], 0)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "data-msg-note")
        Message.objects.filter(thread=thread).update(status="approved")
        heard = self.client.get(reverse("message_ping"))
        data = heard.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["name"], "تهیه‌کننده")
        self.assertIn("فردا", data["preview"])
        self.assertEqual(data["url"], reverse("thread", args=[thread.pk]))
        self.client.logout()
        self.client.login(username="seeker1", password="pass12345")
        self.assertEqual(self.client.get(reverse("message_ping")).json()["count"], 0)
        self.assertContains(self.client.get(reverse("home")), "data-push-enable")
        self.assertContains(self.client.get(reverse("home")), "اعلان پیام")

    def test_phone_notification_goes_to_the_recipient_when_a_message_is_approved(self):
        thread = Thread.between(self.seeker, self.actor)
        message = Message.objects.create(
            thread=thread,
            sender=self.seeker,
            body="فردا سر دستگاه",
            status="pending",
        )
        PushSubscription.objects.create(
            user=self.actor,
            endpoint="https://push.example/actor",
            p256dh="key",
            auth="auth",
        )
        PushSubscription.objects.create(
            user=self.seeker,
            endpoint="https://push.example/sender",
            p256dh="key",
            auth="auth",
        )
        self.client.force_login(self.actor)
        saved = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({
                "endpoint": "https://push.example/actor-2",
                "keys": {"p256dh": "abc", "auth": "def"},
            }),
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(PushSubscription.objects.filter(user=self.actor, endpoint="https://push.example/actor-2").exists())
        refused = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"endpoint": "http://push.example/no", "keys": {"p256dh": "abc", "auth": "def"}}),
            content_type="application/json",
        )
        self.assertEqual(refused.status_code, 400)
        self.client.logout()
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        with patch("talent.push.webpush") as send:
            approved = self.client.post(
                reverse("moderation"),
                {"kind": "message", "id": message.pk, "action": "approve"},
            )
        self.assertRedirects(approved, reverse("moderation"))
        self.assertEqual(send.call_count, 2)
        endpoints = {call.kwargs["subscription_info"]["endpoint"] for call in send.call_args_list}
        self.assertEqual(endpoints, {"https://push.example/actor", "https://push.example/actor-2"})
        payload = json.loads(send.call_args.kwargs["data"])
        self.assertIn("فردا سر دستگاه", payload["body"])
        self.assertEqual(payload["url"], reverse("thread", args=[thread.pk]))
        self.assertEqual(payload["title"], "پیام تازه در فیکسوگرام")
        waiting = Message.objects.create(
            thread=thread,
            sender=self.seeker,
            body="این یکی نرسد",
            status="pending",
        )
        with patch("talent.push.webpush") as send:
            rejected = self.client.post(
                reverse("moderation"),
                {"kind": "message", "id": waiting.pk, "action": "reject"},
            )
        self.assertRedirects(rejected, reverse("moderation"))
        send.assert_not_called()
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, "rejected")

    def test_a_gone_phone_subscription_is_dropped(self):
        from pywebpush import WebPushException

        thread = Thread.between(self.seeker, self.actor)
        message = Message.objects.create(
            thread=thread,
            sender=self.seeker,
            body="سلام",
            status="approved",
        )
        sub = PushSubscription.objects.create(
            user=self.actor,
            endpoint="https://push.example/gone",
            p256dh="key",
            auth="auth",
        )

        class Gone:
            status_code = 410

        with patch("talent.push.webpush", side_effect=WebPushException("gone", response=Gone())):
            from talent.push import notify_message

            self.assertEqual(notify_message(message), 0)
        self.assertFalse(PushSubscription.objects.filter(pk=sub.pk).exists())

    def test_a_rejected_user_sees_the_reason_and_can_apply_again(self):
        user = User.objects.create_user("09124445566", password="pass12345")
        user.profile.display_name = "مینا"
        user.profile.phone = "09124445566"
        user.profile.account_status = "pending"
        user.profile.save()
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        missing = self.client.post(
            reverse("moderation"),
            {"kind": "signup", "id": user.profile.pk, "action": "reject"},
            follow=True,
        )
        self.assertContains(missing, "دلیل را بنویس")
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.account_status, "pending")
        rejected = self.client.post(
            reverse("moderation"),
            {"kind": "signup", "id": user.profile.pk, "action": "reject", "reason": "عکس چهره واضح نیست"},
        )
        self.assertRedirects(rejected, reverse("moderation"))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.account_status, "rejected")
        self.assertEqual(user.profile.rejection_note, "عکس چهره واضح نیست")
        self.client.logout()

        sent, send = self._request_code("09124445566", "4821")
        self.assertRedirects(sent, reverse("login_code"))
        send.assert_called_once()
        entered = self.client.post(reverse("login_code"), {"code": "4821"})
        self.assertRedirects(entered, reverse("dashboard"))
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "عکس چهره واضح نیست")
        self.assertContains(page, "درخواست دوباره")
        again = self.client.post(reverse("dashboard"), {"form": "reapply"})
        self.assertRedirects(again, reverse("dashboard"))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.account_status, "pending")
        self.assertEqual(user.profile.rejection_note, "")
        self.assertContains(self.client.get(reverse("dashboard")), "در جستجو دیده نمی‌شود")

    def _signup(self, phone, name="مینا"):
        return self.client.post(
            reverse("signup"),
            {
                "display_name": name,
                "phone": phone,
                "accepted": "on",
            },
        )

    def _request_code(self, phone, code="4821"):
        with patch("talent.sms.secrets.randbelow", return_value=int(code) - 1000):
            with patch("talent.sms.deliver_code") as send:
                response = self.client.post(reverse("login"), {"phone": phone})
        return response, send

    def test_signup_waits_for_approval_then_login_uses_a_one_time_code(self):
        blocked = self.client.post(
            reverse("signup"),
            {"display_name": "مینا", "phone": "09123334455"},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "شرایط استفاده")
        self.assertFalse(User.objects.filter(profile__phone="09123334455").exists())
        self.assertContains(self.client.get(reverse("terms")), "شماره تماس")
        self.assertContains(self.client.get(reverse("login")), "کد یک‌بارمصرف")
        self.assertNotContains(self.client.get(reverse("login")), "1111")

        with patch("talent.sms.secrets.randbelow", return_value=3821):
            with patch("talent.sms.deliver_code") as send:
                started = self._signup("۰۹۱۲۳۳۳۴۴۵۵")
        self.assertRedirects(started, reverse("login_code"))
        send.assert_called_once_with("09123334455", "4821", "testserver")
        user = User.objects.get(profile__phone="09123334455")
        self.assertEqual(user.username, "09123334455")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.profile.account_status, "pending")
        self.assertEqual(user.profile.display_name, "مینا")
        self.assertIsNotNone(user.profile.accepted_terms_at)

        wrong = self.client.post(reverse("login_code"), {"code": "1111"})
        self.assertContains(wrong, "اشتباه")
        self.assertContains(wrong, "OTPCredential")
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("login_code"), {"code": "4821"})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertContains(self.client.get(reverse("dashboard")), "در جستجو دیده نمی‌شود")
        self.assertNotContains(self.client.get(reverse("home")), f"/p/{user.profile.pk}/")
        self.client.logout()

        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        approved = self.client.post(
            reverse("moderation"),
            {"kind": "signup", "id": user.profile.pk, "action": "approve"},
        )
        self.assertRedirects(approved, reverse("moderation"))
        self.client.logout()
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.account_status, "approved")

        sent, send = self._request_code("0912 333 4455", "4821")
        self.assertRedirects(sent, reverse("login_code"))
        send.assert_called_once_with("09123334455", "4821", "testserver")
        response = self.client.post(reverse("login_code"), {"code": "4821"})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(User.objects.filter(profile__phone="09123334455").count(), 1)

        buffer = BytesIO()
        Image.new("RGB", (12, 8), (20, 80, 140)).save(buffer, format="PNG")
        photo = SimpleUploadedFile("face.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(
            reverse("dashboard"),
            {
                "form": "profile",
                "display_name": "مینا",
                "username": "mina",
                "city": "اصفهان",
                "phone": "09123334455",
                "headline": "",
                "bio": "",
                "avatar": photo,
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(user.username, "mina")
        self.assertTrue(user.profile.avatar)
        page = self.client.get(reverse("profile", args=[user.profile.pk]))
        self.assertContains(page, "نام کاربری: mina")
        ProfileRole.objects.create(
            profile=user.profile,
            role=Role.objects.get(slug="laptop-repair"),
            status=ProfileRole.Status.APPROVED,
        )
        home = self.client.get(reverse("home"))
        self.assertContains(home, user.profile.avatar.url)
        self.client.logout()

        self.client.logout()
        again = self._signup("+989123334455", name="شخص دیگر")
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, "قبلاً ثبت شده")
        self.assertEqual(User.objects.filter(profile__phone="09123334455").count(), 1)
        self.client.force_login(user)
        self.client.post(
            reverse("dashboard"),
            {
                "form": "profile",
                "display_name": "مینا",
                "username": "mina",
                "city": "اصفهان",
                "phone": "09129998877",
                "headline": "",
                "bio": "",
            },
        )
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.phone, "09123334455")

    def test_forgot_username_sends_name_after_code(self):
        user = User.objects.get(profile__phone="09120000000")
        user.username = "mina"
        user.save(update_fields=["username"])
        page = self.client.get(reverse("login"))
        self.assertContains(page, "نام کاربری را فراموش کرده‌ای")

        with patch("talent.sms.secrets.randbelow", return_value=3821):
            with patch("talent.sms.deliver_code"):
                started = self.client.post(
                    reverse("forgot_username"),
                    {"phone": "09120000000"},
                )
        self.assertRedirects(started, reverse("forgot_username_code"))

        with patch("talent.views.deliver_plain") as send_plain:
            done = self.client.post(reverse("forgot_username_code"), {"code": "4821"})
        self.assertEqual(done.status_code, 200)
        self.assertContains(done, "mina")
        send_plain.assert_called_once()
        self.assertIn("mina", send_plain.call_args[0][1])

    def test_forgot_username_without_custom_name_explains_phone_login(self):
        user = User.objects.get(profile__phone="09120000000")
        user.username = user.profile.phone
        user.save(update_fields=["username"])
        with patch("talent.sms.secrets.randbelow", return_value=3821):
            with patch("talent.sms.deliver_code"):
                self.client.post(reverse("forgot_username"), {"phone": "09120000000"})
        with patch("talent.views.deliver_plain") as send_plain:
            done = self.client.post(reverse("forgot_username_code"), {"code": "4821"})
        self.assertContains(done, "نام کاربری جدا")
        self.assertIn("نام کاربری جدا", send_plain.call_args[0][1])

    def test_login_phone_is_locked_and_only_two_extra_photos(self):
        self.client.force_login(self.actor)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "عوض کردن عکس چهره")
        self.assertContains(page, "فقط مدیر")
        self.assertContains(page, "شماره‌ای که به کاربران نمایش داده می‌شود")
        self.assertNotContains(page, 'name="phone"')
        saved = self.client.post(
            reverse("dashboard"),
            {
                "form": "profile",
                "display_name": "نگار",
                "contact_phone": "02144556677",
            },
        )
        self.assertRedirects(saved, reverse("dashboard"))
        self.actor.profile.refresh_from_db()
        self.assertEqual(self.actor.profile.contact_phone, "02144556677")
        self.assertEqual(self.actor.profile.phone, "09120000000")

        def picture():
            buffer = BytesIO()
            Image.new("RGB", (8, 8), (10, 40, 80)).save(buffer, format="PNG")
            return SimpleUploadedFile("extra.png", buffer.getvalue(), content_type="image/png")

        for caption in ("اول", "دوم"):
            self.client.post(
                reverse("dashboard"),
                {"form": "photo", "caption": caption, "image": picture()},
            )
        self.assertEqual(self.actor.profile.photos.count(), 2)
        self.client.post(
            reverse("dashboard"),
            {"form": "photo", "caption": "سوم", "image": picture()},
        )
        self.assertEqual(self.actor.profile.photos.count(), 2)
        self.assertContains(self.client.get(reverse("dashboard")), "هر دو جا پر است")

        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        self.client.post(
            reverse("moderation"),
            {"kind": "phone_edit", "id": self.actor.profile.pk, "phone": "09125556677"},
        )
        self.actor.profile.refresh_from_db()
        self.assertEqual(self.actor.profile.phone, "09125556677")

    def test_blog_categories_and_staff_only_writing(self):
        news = BlogCategory.objects.create(name="اخبار")
        guide = BlogCategory.objects.create(name="آموزش")
        visible = Post.objects.create(
            title="شروع فیلمبرداری",
            category=news,
            body="فردا سر صحنه هستیم.",
            is_published=True,
        )
        hidden = Post.objects.create(
            title="یادداشت خصوصی",
            category=guide,
            body="این را کسی نبیند.",
            is_published=False,
        )
        response = self.client.get(reverse("blog"))
        self.assertContains(response, "شروع فیلمبرداری")
        self.assertContains(response, "اخبار")
        self.assertNotContains(response, "یادداشت خصوصی")
        response = self.client.get(reverse("blog"), {"category": news.pk})
        self.assertContains(response, "شروع فیلمبرداری")
        response = self.client.get(reverse("blog"), {"category": guide.pk})
        self.assertNotContains(response, "شروع فیلمبرداری")
        self.assertEqual(self.client.get(reverse("blog_detail", args=[hidden.pk])).status_code, 404)

        self.client.login(username="seeker1", password="pass12345")
        self.assertEqual(self.client.get(reverse("blog_write")).status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        response = self.client.post(
            reverse("blog_write"),
            {"form": "category", "name": "پشت صحنه"},
        )
        self.assertRedirects(response, reverse("blog_write"))
        self.assertTrue(BlogCategory.objects.filter(name="پشت صحنه").exists())
        response = self.client.post(
            reverse("blog_write"),
            {
                "form": "post",
                "title": "نور صحنه",
                "category": guide.pk,
                "body": "نور را قبل از بازیگر بچین.",
                "is_published": "on",
            },
        )
        created = Post.objects.get(title="نور صحنه")
        self.assertRedirects(response, reverse("blog_detail", args=[created.pk]))
        self.assertContains(self.client.get(reverse("blog")), "نور صحنه")
        self.assertEqual(visible.category.name, "اخبار")
        html_post = self.client.post(
            reverse("blog_write"),
            {
                "form": "post",
                "title": "نمونه HTML",
                "category": guide.pk,
                "body": (
                    '<style>.box{color:#1570d6}</style>'
                    '<section class="box" style="padding:1rem"><h2>تیتر</h2>'
                    '<p>متن <strong>درشت</strong></p>'
                    '<template><div class="card">کارت</div></template>'
                    '</section>'
                    '<script>alert(1)</script>'
                    '<a href="javascript:alert(1)">بد</a>'
                    '<a href="https://example.com">سایت</a>'
                ),
                "is_published": "on",
            },
        )
        created_html = Post.objects.get(title="نمونه HTML")
        self.assertRedirects(html_post, reverse("blog_detail", args=[created_html.pk]))
        page = self.client.get(reverse("blog_detail", args=[created_html.pk]))
        self.assertContains(page, "<h2>تیتر</h2>", html=False)
        self.assertContains(page, "<strong>درشت</strong>", html=False)
        self.assertContains(page, ".box{color:#1570d6}", html=False)
        self.assertContains(page, 'class="box"', html=False)
        self.assertContains(page, 'style="padding:1rem"', html=False)
        self.assertContains(page, "<template>", html=False)
        self.assertContains(page, 'class="card"', html=False)
        self.assertContains(page, "https://example.com")
        self.assertNotContains(page, "alert(1)", html=False)
        self.assertNotContains(page, "javascript:", html=False)

    def test_unapproved_profile_stays_hidden_and_wallet_is_closed(self):
        self.actor.profile.account_status = "pending"
        self.actor.profile.listed_until = None
        self.actor.profile.save()
        self.assertNotContains(self.client.get(reverse("home")), "نگار")
        self.client.login(username="seeker1", password="pass12345")
        hidden = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertEqual(hidden.status_code, 404)
        self.assertNotContains(self.client.get(reverse("home")), "کیف پول")
        self.assertEqual(self.client.get("/wallet/").status_code, 404)
        self.client.logout()

        self.client.login(username="actor1", password="pass12345")
        self.assertEqual(self.client.get(reverse("profile", args=[self.actor.profile.pk])).status_code, 200)
        self.assertNotContains(self.client.get(reverse("dashboard")), "کیف پول")
        self.client.logout()

        self.assertFalse(self.actor.profile.is_public())
        self.assertNotContains(self.client.get(reverse("home")), "نگار")
        self.actor.profile.account_status = "approved"
        self.actor.profile.save(update_fields=["account_status"])
        self.assertTrue(self.actor.profile.is_public())
        self.assertContains(self.client.get(reverse("home")), "نگار")

    def test_staff_can_place_three_linked_banners(self):
        def picture(name):
            buffer = BytesIO()
            Image.new("RGB", (12, 8), (180, 30, 30)).save(buffer, format="PNG")
            return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

        self.client.login(username="seeker1", password="pass12345")
        self.assertEqual(self.client.get(reverse("banners")).status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        page = self.client.get(reverse("banners"))
        self.assertContains(page, "پر شده")
        self.assertContains(page, "باقی‌مانده")
        self.assertContains(page, "۱۲۰۰")
        self.assertContains(page, "۳۰۰")
        self.assertContains(page, "تنظیم می‌شود")
        heavy = SimpleUploadedFile("big.jpg", b"x" * (1024 * 1024 + 1), content_type="image/jpeg")
        rejected = self.client.post(
            reverse("banners"),
            {"title": "سنگین", "link": "https://example.com/heavy", "image": heavy},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertContains(rejected, "تصویر")
        self.assertEqual(Banner.objects.count(), 0)
        added = self.client.post(
            reverse("banners"),
            {"title": "آموزشگاه", "link": "https://example.com/class", "image": picture("a.png")},
        )
        self.assertRedirects(added, reverse("banners"))
        home = self.client.get(reverse("home"))
        school = Banner.objects.get(title="آموزشگاه")
        with Image.open(school.image) as opened:
            self.assertEqual(opened.size, (1200, 300))
        self.assertContains(home, reverse("banner_go", args=[school.pk]))
        self.assertContains(home, "آموزشگاه")
        for number in range(2):
            self.client.post(
                reverse("banners"),
                {
                    "title": f"بنر {number}",
                    "link": f"https://example.com/ad{number}",
                    "image": picture(f"{number}.png"),
                },
            )
        self.assertEqual(Banner.objects.count(), 3)
        blocked = self.client.post(
            reverse("banners"),
            {"title": "اضافه", "link": "https://example.com/no", "image": picture("no.png")},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "۳ بنر پر شده")
        self.assertEqual(Banner.objects.count(), 3)
        home = self.client.get(reverse("home"))
        self.assertContains(home, "banner-dots")
        self.assertContains(home, reverse("banner_go", args=[Banner.objects.get(link="https://example.com/ad0").pk]))
        hidden = Banner.objects.get(link="https://example.com/ad0")
        hidden.is_active = False
        hidden.save(update_fields=["is_active"])
        self.assertNotContains(self.client.get(reverse("home")), "https://example.com/ad0")
        self.client.post(reverse("delete_banner", args=[hidden.pk]))
        self.assertEqual(Banner.objects.count(), 2)
        kept = Banner.objects.get(title="آموزشگاه")
        replaced = self.client.post(
            reverse("banners"),
            {
                "form": "edit",
                "id": kept.pk,
                "place": "home",
                "title": "آموزشگاه تازه",
                "link": "https://example.com/class-new",
            },
        )
        self.assertRedirects(replaced, reverse("banners"))
        kept.refresh_from_db()
        self.assertEqual(kept.title, "آموزشگاه تازه")
        self.assertEqual(kept.link, "https://example.com/class-new")
        self.assertTrue(kept.image)
        board = self.client.get(reverse("banners"))
        self.assertContains(board, "banner-card")
        self.assertContains(board, "آموزشگاه تازه")

    def test_each_category_shows_two_small_banners(self):
        def picture(name):
            buffer = BytesIO()
            Image.new("RGB", (40, 16), (20, 90, 160)).save(buffer, format="PNG")
            return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("banners"))
        self.assertContains(page, "۵۶۰")
        self.assertContains(page, "۱۶۰")
        self.assertContains(page, "تنظیم می‌شود")
        laptop = Category.objects.get(slug="laptop")
        for number in range(2):
            added = self.client.post(
                reverse("banners"),
                {
                    "title": f"تبلیغ لپ‌تاپ {number}",
                    "link": f"https://example.com/laptop{number}",
                    "place": "section",
                    "category": laptop.pk,
                    "image": picture(f"lap{number}.png"),
                },
            )
            self.assertRedirects(added, reverse("banners"))
        blocked = self.client.post(
            reverse("banners"),
            {
                "title": "اضافه",
                "link": "https://example.com/extra",
                "place": "section",
                "category": laptop.pk,
                "image": picture("extra.png"),
            },
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "دو بنر")
        fitted = Banner.objects.get(link="https://example.com/laptop0")
        with Image.open(fitted.image) as opened:
            self.assertEqual(opened.size, (560, 160))
        section = self.client.get(reverse("section", args=["laptop"]))
        self.assertContains(section, "banner-pair")
        self.assertContains(section, reverse("banner_go", args=[Banner.objects.get(link="https://example.com/laptop0").pk]))
        self.assertContains(section, reverse("banner_go", args=[Banner.objects.get(link="https://example.com/laptop1").pk]))
        self.assertNotContains(section, "https://example.com/extra")

    def test_a_large_face_photo_is_shrunk_before_it_is_stored(self):
        self.client.login(username="actor1", password="pass12345")
        buffer = BytesIO()
        Image.frombytes("RGB", (1400, 1000), os.urandom(1400 * 1000 * 3)).save(buffer, format="JPEG", quality=90)
        photo = SimpleUploadedFile("face.jpg", buffer.getvalue(), content_type="image/jpeg")
        saved = self.client.post(
            reverse("dashboard"),
            {
                "form": "profile",
                "display_name": "نگار",
                "city": "تهران",
                "phone": "09120000000",
                "avatar": photo,
            },
        )
        self.assertRedirects(saved, reverse("dashboard"))
        self.actor.profile.refresh_from_db()
        self.assertTrue(self.actor.profile.avatar.name.endswith(".jpg"))
        self.assertLess(self.actor.profile.avatar.size, 220 * 1024)
        with Image.open(self.actor.profile.avatar) as opened:
            self.assertEqual(max(opened.size), 800)

    def test_banner_clicks_export_for_the_chosen_range(self):
        from talent.dates import gregorian_to_jalali, jalali_label
        from talent.models import BannerClick

        self.assertEqual(gregorian_to_jalali(2024, 3, 20), (1403, 1, 1))
        from datetime import date as gregorian_date
        from talent.dates import jalali_to_gregorian, parse_day

        for sample in (gregorian_date(2024, 3, 20), gregorian_date(2026, 10, 5), gregorian_date(2099, 1, 1)):
            converted = gregorian_to_jalali(sample.year, sample.month, sample.day)
            self.assertEqual(jalali_to_gregorian(*converted), sample)
        self.assertEqual(parse_day("۱۴۰۵/۰۷/۱۳"), gregorian_date(2026, 10, 5))
        buffer = BytesIO()
        Image.new("RGB", (12, 8), (20, 80, 140)).save(buffer, format="PNG")
        picture = SimpleUploadedFile("ad.png", buffer.getvalue(), content_type="image/png")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        self.client.post(
            reverse("banners"),
            {"title": "آموزشگاه کلیک", "link": "https://example.com/class", "image": picture},
        )
        banner = Banner.objects.get(title="آموزشگاه کلیک")
        self.client.logout()
        denied = self.client.get(reverse("banner_report"))
        self.assertEqual(denied.status_code, 302)
        clicked = self.client.get(reverse("banner_go", args=[banner.pk]))
        self.assertRedirects(clicked, "https://example.com/class", fetch_redirect_response=False)
        old = BannerClick.objects.get()
        old.clicked_at = timezone.now() - timedelta(days=40)
        old.save(update_fields=["clicked_at"])
        self.client.get(reverse("banner_go", args=[banner.pk]))
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("banners"))
        self.assertContains(page, "کلیک: امروز")
        report = self.client.get(reverse("banner_report"), {"range": "7"})
        self.assertContains(report, "آموزشگاه کلیک")
        self.assertContains(report, jalali_label(timezone.localdate()))
        self.assertContains(report, "data-jalali")
        self.assertNotContains(report, 'type="date"')
        exported = self.client.get(reverse("banner_report"), {"range": "7", "export": "csv"})
        body = exported.content.decode("utf-8-sig")
        self.assertIn("تعداد کلیک", body)
        self.assertIn("آموزشگاه کلیک", body)
        self.assertIn("جمع بازه", body)
        self.assertEqual(body.count("روزانه"), 1)
        month = self.client.get(reverse("banner_report"), {"range": "90", "export": "csv"})
        self.assertEqual(month.content.decode("utf-8-sig").count("روزانه"), 2)

    def test_reports_show_visits_and_people_online(self):
        from talent.models import PageView, Presence

        denied = self.client.get(reverse("reports"))
        self.assertEqual(denied.status_code, 302)
        self.client.get(reverse("home"))
        self.client.get(reverse("jobs"))
        self.assertGreaterEqual(PageView.objects.filter(path="/").count(), 1)
        gone = User.objects.create_user("gone")
        gone.profile.display_name = "قدیمی"
        gone.profile.save()
        Presence.objects.create(
            session_key="gone-key",
            user=gone,
            path="/",
            last_seen=timezone.now() - timedelta(minutes=30),
        )
        Presence.objects.create(
            session_key="guest-key",
            path="/jobs/",
            last_seen=timezone.now(),
        )
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("reports"))
        self.assertContains(page, "افراد آنلاین")
        self.assertContains(page, "تهیه‌کننده")
        self.assertContains(page, "مهمان")
        self.assertNotContains(page, "قدیمی")
        exported = self.client.get(reverse("visit_report"), {"range": "today", "export": "csv"})
        body = exported.content.decode("utf-8-sig")
        self.assertIn("بازدید", body)
        self.assertIn("نفر", body)
        self.assertIn("صفحه جستجو", body)
        self.assertIn("جمع بازه", body)

    def test_staff_desk_lists_the_site_queues(self):
        self.client.login(username="seeker1", password="pass12345")
        denied = self.client.get(reverse("desk"))
        self.assertEqual(denied.status_code, 302)
        hidden = self.client.get(reverse("home"))
        self.assertNotContains(hidden, "online-pill")
        self.seeker.is_staff = True
        self.seeker.save()
        page = self.client.get(reverse("desk"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ثبت‌نام منتظر")
        self.assertContains(page, "online-now")
        self.assertContains(page, "online-pill")
        self.assertContains(page, "آگهی کار منتظر")
        self.assertContains(page, "بنرها")
        self.assertContains(page, "اطلاعیه")
        self.assertContains(page, "نفر آنلاین")
        self.assertContains(page, "online-bar")
        self.assertNotContains(page, "کیف پول")

    def test_only_staff_can_open_moderation(self):
        self.client.login(username="seeker1", password="pass12345")
        response = self.client.get(reverse("moderation"))
        self.assertEqual(response.status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        response = self.client.get(reverse("moderation"))
        self.assertEqual(response.status_code, 200)

    def test_welcome_message_plays_once_for_a_new_visit(self):
        self.client.login(username="seeker1", password="pass12345")
        denied = self.client.post(reverse("dashboard"), {"form": "welcome", "body": "نباید ذخیره شود"})
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(WelcomeMessage.objects.count(), 0)
        self.assertNotContains(denied, "پیام مدیر برای تازه‌واردها")

        self.seeker.is_staff = True
        self.seeker.save()
        audio = SimpleUploadedFile("hello.mp3", b"fake-audio", content_type="audio/mpeg")
        saved = self.client.post(
            reverse("dashboard"),
            {"form": "welcome", "body": "سلام تازه‌وارد", "audio": audio, "is_active": "on"},
        )
        self.assertRedirects(saved, reverse("dashboard"))
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "سلام تازه‌وارد")
        self.assertContains(page, "hello.mp3")
        own_profile = self.client.get(reverse("profile", args=[self.seeker.profile.pk]))
        self.assertContains(own_profile, "سلام تازه‌وارد")

        self.client.logout()
        self.client.login(username="actor1", password="pass12345")
        self.assertContains(self.client.get(reverse("dashboard")), "سلام تازه‌وارد")
        self.assertContains(self.client.get(reverse("profile", args=[self.actor.profile.pk])), "سلام تازه‌وارد")
        self.client.logout()
        self.client.login(username="outsider", password="pass12345")
        self.assertContains(self.client.get(reverse("profile", args=[self.actor.profile.pk])), "سلام تازه‌وارد")
        self.client.logout()
        self.client.login(username="actor1", password="pass12345")
        self.client.post(reverse("dashboard"), {"form": "welcome-seen"})
        self.assertNotContains(self.client.get(reverse("dashboard")), "سلام تازه‌وارد")

        note = WelcomeMessage.objects.get()
        note.body = "نسخه تازه"
        note.save()
        self.assertContains(self.client.get(reverse("dashboard")), "نسخه تازه")
        heavy = SimpleUploadedFile("big.mp4", b"x" * (8 * 1024 * 1024 + 1), content_type="video/mp4")
        self.client.logout()
        self.client.login(username="seeker1", password="pass12345")
        rejected = self.client.post(
            reverse("dashboard"),
            {"form": "welcome", "body": "نسخه تازه", "video": heavy, "is_active": "on"},
        )
        self.assertContains(rejected, "۸ مگابایت")
        note.audio.delete(save=False)
        note.delete()

    def test_visitor_can_hide_the_prepared_welcome(self):
        WelcomeMessage.objects.create(body="خوش آمدی به فیکسوگرام")
        first = self.client.get(reverse("home"))
        self.assertContains(first, "خوش آمدی به فیکسوگرام")
        self.assertContains(first, "دیگر نمایش نده")
        self.client.post(reverse("dismiss_welcome"), {"next": "/"})
        self.assertNotContains(self.client.get(reverse("home")), "خوش آمدی به فیکسوگرام")
        note = WelcomeMessage.objects.get()
        note.is_active = False
        note.save()
        fresh = self.client.__class__()
        self.assertNotContains(fresh.get(reverse("home")), "خوش آمدی به فیکسوگرام")

    def test_user_can_ticket_management_and_report_a_profile(self):
        self.client.login(username="outsider", password="pass12345")
        denied = self.client.get(reverse("support"))
        self.assertEqual(denied.status_code, 302)
        filed = self.client.post(
            reverse("tickets"),
            {"subject": "صفحه من باز نمی‌شود", "body": "بعد از ورود، تخصص‌ها ذخیره نمی‌شوند."},
        )
        self.assertRedirects(filed, reverse("tickets"))
        self.assertContains(self.client.get(reverse("tickets")), "صفحه من باز نمی‌شود")
        self_report = self.client.get(reverse("report_profile", args=[self.outsider.profile.pk]))
        self.assertRedirects(self_report, reverse("profile", args=[self.outsider.profile.pk]))
        reported = self.client.post(
            reverse("report_profile", args=[self.actor.profile.pk]),
            {"reason": "fake", "body": "شهر و تخصص با کار واقعی فرق دارد."},
        )
        self.assertRedirects(reported, reverse("profile", args=[self.actor.profile.pk]))
        self.client.logout()
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        desk = self.client.get(reverse("support"))
        self.assertContains(desk, "صفحه من باز نمی‌شود")
        self.assertContains(desk, "شهر و تخصص با کار واقعی فرق دارد.")
        from talent.models import Ticket

        ticket = Ticket.objects.get()
        answered = self.client.post(
            reverse("support"),
            {"kind": "ticket", "id": ticket.pk, "action": "reply", "reply": "دوباره تخصص را ذخیره کن."},
        )
        self.assertRedirects(answered, reverse("support"))
        self.client.logout()
        self.client.login(username="outsider", password="pass12345")
        self.assertContains(self.client.get(reverse("tickets")), "دوباره تخصص را ذخیره کن.")

    def test_manager_can_message_everyone_in_a_category(self):
        denied = self.client.get(reverse("broadcast"))
        self.assertEqual(denied.status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        laptop = Category.objects.get(slug="laptop")
        sent = self.client.post(
            reverse("broadcast"),
            {"category": laptop.pk, "body": "فردا کارگاه لپ‌تاپ تعطیل است."},
        )
        self.assertRedirects(sent, reverse("broadcast"))
        self.client.logout()
        self.client.login(username="actor1", password="pass12345")
        inbox = self.client.get(reverse("inbox"))
        self.assertContains(inbox, "فردا کارگاه لپ‌تاپ تعطیل است.")
        self.client.logout()
        self.client.login(username="outsider", password="pass12345")
        self.assertNotContains(self.client.get(reverse("inbox")), "فردا کارگاه لپ‌تاپ تعطیل است.")

    def test_admin_phone_is_the_only_manager(self):
        other = User.objects.create_user("other-admin", password="pass12345")
        other.is_staff = True
        other.is_superuser = True
        other.save()
        other.profile.phone = "09120000099"
        other.profile.save()
        manager = User.objects.create_user("09124770435", password="1111")
        manager.profile.phone = "09124770435"
        manager.profile.save()

        call_command("ensure_admin")
        manager.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(manager.is_staff)
        self.assertTrue(manager.is_superuser)
        self.assertFalse(manager.has_usable_password())
        self.assertFalse(manager.check_password("1111"))
        self.assertFalse(other.is_staff)
        self.assertFalse(other.is_superuser)

    def test_same_phone_does_not_create_a_second_account(self):
        first = self._signup("09125556677", name="کیان")
        self.assertRedirects(first, reverse("login"))
        again = self._signup("09125556677", name="کیان")
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, "قبلاً ثبت شده")
        self.assertEqual(User.objects.filter(profile__phone="09125556677").count(), 1)

    def test_same_phone_variant_formats_cannot_signup_twice(self):
        first = self._signup("09128887766", name="سارا")
        self.assertRedirects(first, reverse("login"))
        again = self._signup("+989128887766", name="سارا ۲")
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, "قبلاً ثبت شده")
        self.assertEqual(User.objects.filter(profile__phone="09128887766").count(), 1)

    def test_manager_can_archive_or_delete_an_account(self):
        manager = User.objects.create_user("09124770435")
        manager.is_staff = True
        manager.is_superuser = True
        manager.save()
        self.client.force_login(manager)
        bare = self.client.get(reverse("system_users"))
        self.assertNotContains(bare, "09120000000")
        page = self.client.get(reverse("system_users"), {"q": "نگار"})
        self.assertContains(page, "بایگانی")
        self.assertContains(page, "نگار")

        archived = self.client.post(
            reverse("system_users"),
            {"kind": "account", "id": self.actor.profile.pk, "action": "archive"},
        )
        self.assertRedirects(archived, reverse("system_users"))
        self.assertNotContains(self.client.get(reverse("home")), "نگار")
        self.client.force_login(self.actor)
        own = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(own, "بایگانی")
        self.client.logout()
        self.client.force_login(self.outsider)
        hidden = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertEqual(hidden.status_code, 404)

        self.client.force_login(manager)
        denied = self.client.post(
            reverse("system_users"),
            {"kind": "account", "id": manager.profile.pk, "action": "delete"},
        )
        self.assertRedirects(denied, reverse("system_users"))
        self.assertTrue(User.objects.filter(pk=manager.pk).exists())
        deleted = self.client.post(
            reverse("system_users"),
            {"kind": "account", "id": self.actor.profile.pk, "action": "delete"},
        )
        self.assertRedirects(deleted, reverse("system_users"))
        self.assertFalse(User.objects.filter(username="actor1").exists())

    def test_manager_filters_users_by_identity_city_time_violation_and_score(self):
        self.actor.profile.is_vip = True
        self.actor.profile.staff_score = 4
        self.actor.profile.save(update_fields=["is_vip", "staff_score"])
        ViolationReport.objects.create(
            reporter=self.seeker,
            profile=self.actor.profile,
            reason="fake",
            body="تخلف تست",
        )
        manager = User.objects.create_superuser("manager-filter", "filter@example.com", "pass12345")
        self.client.force_login(manager)
        bare = self.client.get(reverse("system_users"))
        self.assertContains(bare, "ابراز هویت")
        self.assertContains(bare, "تخلف‌دارها")
        self.assertContains(bare, "جستجو کن")
        self.assertNotContains(bare, ">نگار<")
        self.assertContains(self.client.get(reverse("system_users"), {"identity": "yes"}), "نگار")
        self.assertNotContains(self.client.get(reverse("system_users"), {"identity": "no"}), "نگار")
        self.assertContains(self.client.get(reverse("system_users"), {"city": "تهران"}), "نگار")
        self.assertNotContains(self.client.get(reverse("system_users"), {"city": "اصفهان"}), "نگار")
        self.assertContains(self.client.get(reverse("system_users"), {"violation": "yes"}), "نگار")
        self.assertContains(self.client.get(reverse("system_users"), {"score": "4"}), "نگار")
        self.assertNotContains(self.client.get(reverse("system_users"), {"score": "1"}), "نگار")
        from talent.dates import jalali_label

        today = timezone.localdate().isoformat()
        ranged = self.client.get(reverse("system_users"), {"start": today, "end": today})
        self.assertContains(ranged, "نگار")
        self.assertContains(ranged, "data-jalali")
        self.assertContains(ranged, jalali_label(timezone.localdate()))
        self.assertNotContains(ranged, 'type="date"')
        self.assertNotContains(self.client.get(reverse("system_users"), {"start": "2099-01-01"}), "نگار")
        self.assertNotContains(self.client.get(reverse("system_users"), {"start": "۱۴۱۰/۰۱/۰۱"}), "نگار")

    def test_manager_can_search_and_deactivate_a_user(self):
        self.actor.profile.business_name = "تعمیرگاه نگار"
        self.actor.profile.bio = "تعمیر برد لپ‌تاپ"
        self.actor.profile.contact_phone = "02144556677"
        self.actor.profile.save(update_fields=["business_name", "bio", "contact_phone"])
        manager = User.objects.create_user("09124770436")
        manager.is_staff = True
        manager.is_superuser = True
        manager.save()
        self.client.force_login(manager)
        page = self.client.get(reverse("system_users"))
        self.assertContains(page, "کاربر در سیستم")
        self.assertNotContains(page, "غیرفعال")
        self.assertContains(page, "جستجو کن")
        by_business = self.client.get(reverse("system_users"), {"q": "تعمیرگاه"})
        self.assertContains(by_business, "02144556677")
        self.assertContains(by_business, "شماره‌ای که به کاربران نمایش داده می‌شود")
        self.assertContains(by_business, "تعمیر برد لپ‌تاپ")
        self.assertContains(by_business, "توضیحات")
        self.assertContains(by_business, "گردش مالی")
        self.assertContains(by_business, "هنوز گردشی ثبت نشده")
        self.assertContains(by_business, "ویرایش کارتابل")
        edited = self.client.post(
            reverse("system_users"),
            {
                "kind": "edit-profile",
                "id": self.actor.profile.pk,
                "filter_q": "تعمیرگاه",
                "display_name": "نگار رضایی",
                "business_name": "تعمیرگاه نگار",
                "headline": "تعمیر تخصصی",
                "city": "اصفهان",
                "contact_phone": "03132221100",
                "bio": "متن تازه کارتابل",
                "about_business": "معرفی مجموعه تازه",
                "instagram": "negar.repair",
            },
        )
        self.assertRedirects(edited, f"{reverse('system_users')}?q=%D8%AA%D8%B9%D9%85%DB%8C%D8%B1%DA%AF%D8%A7%D9%87")
        self.actor.profile.refresh_from_db()
        self.assertEqual(self.actor.profile.display_name, "نگار رضایی")
        self.assertEqual(self.actor.profile.city, "اصفهان")
        self.assertEqual(self.actor.profile.province, "اصفهان")
        self.assertEqual(self.actor.profile.contact_phone, "03132221100")
        self.assertEqual(self.actor.profile.bio, "متن تازه کارتابل")
        self.assertEqual(self.actor.profile.instagram, "negar.repair")
        self.assertEqual(self.actor.profile.instagram_url, "https://instagram.com/negar.repair")
        self.actor.profile.whatsapp = "09121112233"
        self.assertEqual(self.actor.profile.whatsapp_url, "https://wa.me/989121112233")
        self.assertEqual(self.actor.profile.phone, "09120000000")
        shown = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(shown, "social-logo ig")
        self.assertContains(shown, "https://instagram.com/negar.repair")
        self.assertContains(shown, 'aria-label="اینستاگرام"')
        by_phone = self.client.get(reverse("system_users"), {"q": "09120000000"})
        self.assertContains(by_phone, "نگار")
        self.assertContains(by_phone, "social-logo ig")
        missed = self.client.get(reverse("system_users"), {"q": "چیزناموجود"})
        self.assertContains(missed, "پیدا نشد")
        self.assertNotContains(missed, "09120000000")
        off = self.client.post(
            reverse("system_users"),
            {
                "kind": "account",
                "id": self.actor.profile.pk,
                "action": "deactivate",
                "filter_q": "نگار",
            },
        )
        self.assertRedirects(off, f"{reverse('system_users')}?q=%D9%86%DA%AF%D8%A7%D8%B1")
        self.actor.refresh_from_db()
        self.assertFalse(self.actor.is_active)
        self.assertNotContains(self.client.get(reverse("home")), "نگار")
        self.client.logout()
        blocked = self.client.post(reverse("login"), {"phone": "09120000000"})
        self.assertContains(blocked, "غیرفعال")
        self.client.force_login(manager)
        self.client.post(
            reverse("system_users"),
            {"kind": "account", "id": self.actor.profile.pk, "action": "activate"},
        )
        self.actor.refresh_from_db()
        self.assertTrue(self.actor.is_active)

    def test_staff_can_delete_a_profile_from_its_page(self):
        self.client.force_login(self.outsider)
        hidden = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertNotContains(hidden, "حذف پروفایل")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(page, "حذف پروفایل")
        removed = self.client.post(
            reverse("moderation"),
            {"kind": "account", "id": self.actor.profile.pk, "action": "delete"},
        )
        self.assertRedirects(removed, reverse("moderation"))
        self.assertFalse(User.objects.filter(pk=self.actor.pk).exists())

    def test_job_post_stays_hidden_until_approved(self):
        self.client.login(username="actor1", password="pass12345")
        posted = self.client.post(
            reverse("jobs"),
            {
                "kind": "hire",
                "title": "تعمیرکار لپ‌تاپ می‌خواهیم",
                "city": "کرج",
                "duration_days": "7",
                "body": "برای کارگاه، یک نفر آشنا به لپ‌تاپ لازم است.",
            },
        )
        self.assertRedirects(posted, reverse("jobs"))
        post = JobPost.objects.get()
        self.assertEqual(post.status, JobPost.Status.PENDING)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("job_detail", args=[post.pk])).status_code, 404)
        hidden = self.client.get(reverse("jobs"))
        self.assertNotContains(hidden, "تعمیرکار لپ‌تاپ می‌خواهیم")
        self.assertContains(hidden, "استخدام")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        approved = self.client.post(
            reverse("moderation"),
            {"kind": "job", "id": post.pk, "action": "approve"},
        )
        self.assertRedirects(approved, reverse("moderation"))
        self.client.logout()
        public = self.client.get(reverse("jobs"), {"kind": "hire", "q": "لپ‌تاپ"})
        self.assertContains(public, "تعمیرکار لپ‌تاپ می‌خواهیم")
        self.assertContains(public, "درخواست‌کننده")
        self.assertContains(public, reverse("job_detail", args=[post.pk]))
        detail = self.client.get(reverse("job_detail", args=[post.pk]))
        self.assertContains(detail, "درخواست‌کننده")
        self.assertContains(detail, "نگار")
        self.assertContains(detail, "چت با درخواست‌کننده")
        self.assertContains(detail, reverse("start_thread", args=[self.actor.profile.pk]))
        self.assertContains(public, "روز مانده")
        self.assertContains(self.client.get(reverse("home"), {"q": "لپ‌تاپ"}), "تعمیرکار لپ‌تاپ می‌خواهیم")
        post.refresh_from_db()
        self.assertEqual(post.duration_days, 7)
        self.assertGreater(post.expires_at, timezone.now() + timedelta(days=6))

    def test_job_post_is_deleted_after_the_chosen_time(self):
        self.client.login(username="actor1", password="pass12345")
        form_page = self.client.get(reverse("jobs"))
        self.assertContains(form_page, "۷ روز")
        self.assertContains(form_page, "۱۵ روز")
        self.assertContains(form_page, "یک ماه")
        self.client.post(
            reverse("jobs"),
            {
                "kind": "seek",
                "title": "دنبال کار مانیتور",
                "city": "تهران",
                "duration_days": "15",
                "body": "تعمیر مانیتور بلدم.",
            },
        )
        post = JobPost.objects.get(title="دنبال کار مانیتور")
        self.assertEqual(post.duration_days, 15)
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        self.client.post(reverse("moderation"), {"kind": "job", "id": post.pk, "action": "approve"})
        post.refresh_from_db()
        self.assertEqual(post.duration_days, 15)
        post.expires_at = timezone.now() - timedelta(minutes=1)
        post.save(update_fields=["expires_at"])
        page = self.client.get(reverse("jobs"))
        self.assertNotContains(page, "دنبال کار مانیتور")
        self.assertFalse(JobPost.objects.filter(pk=post.pk).exists())

    def test_job_views_warning_and_report_cover_hire_and_seek(self):
        self.actor.profile.account_status = "approved"
        self.actor.profile.save(update_fields=["account_status"])
        self.client.login(username="actor1", password="pass12345")
        for kind, title in (("hire", "آگهی نیرو برای کارگاه"), ("seek", "آگهی آماده به کار")):
            self.client.post(
                reverse("jobs"),
                {
                    "kind": kind,
                    "title": title,
                    "city": "اصفهان",
                    "duration_days": "7",
                    "body": "شرح آگهی برای همکاری.",
                },
            )
        hire = JobPost.objects.get(title="آگهی نیرو برای کارگاه")
        seek = JobPost.objects.get(title="آگهی آماده به کار")
        self.seeker.is_staff = True
        self.seeker.is_superuser = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        desk = self.client.get(reverse("desk"))
        self.assertContains(desk, 'name="job_warning"')
        self.assertContains(desk, "زنگ خطر قبل از همکاری")
        saved = self.client.post(
            reverse("desk"),
            {"form": "job_warning", "job_warning": "قبل از هر همکاری مدارک را ببین."},
        )
        self.assertRedirects(saved, reverse("desk"))
        for post in (hire, seek):
            self.client.post(
                reverse("moderation"),
                {"kind": "job", "id": post.pk, "action": "approve"},
            )
        self.client.logout()
        guest = self.client.get(reverse("job_detail", args=[hire.pk]))
        self.assertContains(guest, "قبل از هر همکاری مدارک را ببین.")
        self.assertContains(guest, "گزارش تخلف")
        self.assertNotContains(guest, "بازدید")
        seek_page = self.client.get(reverse("job_detail", args=[seek.pk]))
        self.assertContains(seek_page, "زنگ خطر قبل از همکاری")
        self.assertContains(seek_page, "گزارش تخلف")
        self.client.login(username="actor1", password="pass12345")
        own = self.client.get(reverse("job_detail", args=[hire.pk]))
        self.assertContains(own, "بازدید ۱")
        self.assertContains(own, "۱ نفر")
        self.assertNotContains(own, reverse("report_job", args=[hire.pk]))
        mine = self.client.get(reverse("jobs"))
        self.assertContains(mine, "بازدید ۱")
        blocked = self.client.get(reverse("report_job", args=[hire.pk]))
        self.assertRedirects(blocked, reverse("job_detail", args=[hire.pk]))
        self.client.logout()
        self.client.login(username="outsider", password="pass12345")
        stranger = self.client.get(reverse("job_detail", args=[hire.pk]))
        self.assertNotContains(stranger, "بازدید")
        reported = self.client.post(
            reverse("report_job", args=[seek.pk]),
            {"reason": "scam", "body": "این آگهی آماده به کار مشکوک است."},
        )
        self.assertRedirects(reported, reverse("job_detail", args=[seek.pk]))
        self.assertTrue(ViolationReport.objects.filter(job=seek, reason="scam").exists())
        self.client.logout()
        self.client.force_login(self.seeker)
        support = self.client.get(reverse("support"))
        self.assertContains(support, "این آگهی آماده به کار مشکوک است.")
        self.assertContains(support, reverse("job_detail", args=[seek.pk]))
        staff_view = self.client.get(reverse("job_detail", args=[hire.pk]))
        self.assertContains(staff_view, "بازدید ۲")
        cleared = self.client.post(reverse("desk"), {"form": "job_warning", "job_warning": "  "})
        self.assertRedirects(cleared, reverse("desk"))
        self.client.logout()
        fallback = self.client.get(reverse("job_detail", args=[seek.pk]))
        self.assertContains(fallback, "قبل از همکاری هویت طرف را بررسی کن")

    def test_visible_dates_use_jalali(self):
        from talent.dates import jalali_datetime, jalali_label
        from talent.templatetags.talent_tags import jalali, jalali_dt

        moment = timezone.now()
        self.assertEqual(jalali(moment), jalali_label(timezone.localtime(moment).date()))
        self.assertEqual(jalali_dt(moment), jalali_datetime(timezone.localtime(moment)))
        news = BlogCategory.objects.create(name="تاریخ شمسی")
        post = Post.objects.create(
            title="نوشته با تاریخ شمسی",
            category=news,
            body="<p>متن نوشته برای تاریخ.</p>",
            is_published=True,
            author=self.actor,
        )
        page = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(page, jalali_label(timezone.localtime(post.created_at).date()))
        self.assertNotContains(page, post.created_at.strftime("%Y/%m/%d"))
        listing = self.client.get(reverse("blog"))
        self.assertContains(listing, jalali_label(timezone.localtime(post.created_at).date()))

    def test_user_can_save_share_and_unsave(self):
        laptop = Category.objects.get(slug="laptop")
        guest = self.client.get(reverse("section", args=["laptop"]))
        self.assertContains(guest, 'aria-label="اشتراک"')
        self.assertContains(guest, "share-icon")
        self.assertContains(guest, "save-icon")
        self.assertContains(guest, "کپی لینک")
        self.assertContains(guest, "t.me/share")
        self.assertContains(guest, "wa.me/")
        self.assertContains(guest, reverse("login"))
        self.assertNotContains(guest, "navigator.share")
        home = self.client.get(reverse("home"))
        self.assertContains(home, "data-copy-link")
        self.assertNotContains(home, "navigator.share")
        denied = self.client.get(reverse("bookmarks"))
        self.assertEqual(denied.status_code, 302)
        self.client.login(username="actor1", password="pass12345")
        saved = self.client.post(
            reverse("toggle_bookmark"),
            {"kind": "section", "id": laptop.pk, "next": reverse("section", args=["laptop"])},
        )
        self.assertRedirects(saved, reverse("section", args=["laptop"]))
        marked = self.client.get(reverse("section", args=["laptop"]))
        self.assertContains(marked, 'aria-label="برداشتن از ذخیره"')
        self.assertContains(marked, "is-saved")
        self.client.post(
            reverse("toggle_bookmark"),
            {"kind": "profile", "id": self.actor.profile.pk, "next": reverse("bookmarks")},
        )
        job = JobPost.objects.create(
            author=self.seeker,
            kind="seek",
            title="آگهی آماده برای ذخیره",
            body="شرح آگهی ذخیره.",
            city="کرج",
            status=JobPost.Status.APPROVED,
            duration_days=7,
            expires_at=timezone.now() + timedelta(days=7),
        )
        news = BlogCategory.objects.create(name="آموزش ذخیره")
        post = Post.objects.create(
            title="نوشته قابل ذخیره",
            category=news,
            body="<p>متن نوشته.</p>",
            is_published=True,
            author=self.actor,
        )
        self.assertContains(self.client.get(reverse("job_detail", args=[job.pk])), 'aria-label="اشتراک"')
        self.assertContains(self.client.get(reverse("blog_detail", args=[post.pk])), "share-icon")
        self.assertContains(self.client.get(reverse("profile", args=[self.actor.profile.pk])), "save-icon")
        self.client.post(
            reverse("toggle_bookmark"),
            {"kind": "job", "id": job.pk, "next": reverse("bookmarks")},
        )
        self.client.post(
            reverse("toggle_bookmark"),
            {"kind": "post", "id": post.pk, "next": "//evil.example"},
        )
        listing = self.client.get(reverse("bookmarks"))
        self.assertContains(listing, reverse("section", args=["laptop"]))
        self.assertContains(listing, "نگار")
        self.assertContains(listing, "آگهی آماده برای ذخیره")
        self.assertContains(listing, "نوشته قابل ذخیره")
        self.assertContains(listing, "برداشتن از ذخیره")
        self.assertRedirects(
            self.client.post(
                reverse("toggle_bookmark"),
                {"kind": "section", "id": laptop.pk, "next": reverse("bookmarks")},
            ),
            reverse("bookmarks"),
        )
        cleared = self.client.get(reverse("bookmarks"))
        self.assertNotContains(cleared, reverse("section", args=["laptop"]))
        self.assertContains(cleared, "آگهی آماده برای ذخیره")

    def test_manager_can_edit_and_delete_hire_and_seek_ads(self):
        hire = JobPost.objects.create(
            author=self.actor,
            kind="hire",
            title="آگهی استخدام پنل",
            body="شرح استخدام.",
            city="کرج",
            status=JobPost.Status.PENDING,
            duration_days=7,
        )
        seek = JobPost.objects.create(
            author=self.actor,
            kind="seek",
            title="آگهی آماده پنل",
            body="شرح آماده به کار.",
            city="اصفهان",
            status=JobPost.Status.APPROVED,
            duration_days=7,
            reviewed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.login(username="outsider", password="pass12345")
        self.assertEqual(self.client.get(reverse("manage_jobs")).status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        desk = self.client.get(reverse("desk"))
        self.assertContains(desk, "استخدام و آماده به کار")
        board = self.client.get(reverse("manage_jobs"))
        self.assertContains(board, "آگهی استخدام پنل")
        self.assertContains(board, "آگهی آماده پنل")
        self.assertContains(board, "ویرایش")
        self.assertContains(board, "حذف")
        ready = self.client.get(reverse("manage_jobs"), {"kind": "seek"})
        self.assertContains(ready, "آگهی آماده پنل")
        self.assertNotContains(ready, "آگهی استخدام پنل")
        edited = self.client.post(
            reverse("manage_jobs"),
            {
                "action": "save",
                "id": hire.pk,
                "kind": "hire",
                "title": "عنوان استخدام عوض شد",
                "city": "رشت",
                "duration_days": "15",
                "body": "شرح تازه استخدام.",
            },
        )
        self.assertRedirects(edited, reverse("manage_jobs"))
        hire.refresh_from_db()
        self.assertEqual(hire.title, "عنوان استخدام عوض شد")
        self.assertEqual(hire.city, "رشت")
        self.assertEqual(hire.status, JobPost.Status.PENDING)
        removed = self.client.post(
            reverse("manage_jobs"),
            {"action": "delete", "id": seek.pk},
        )
        self.assertRedirects(removed, reverse("manage_jobs"))
        self.assertFalse(JobPost.objects.filter(pk=seek.pk).exists())

    def test_expired_code_and_kavenegar_lookup(self):
        LoginCode.objects.create(
            phone="09120000000",
            code_hash=make_password("4821"),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        session = self.client.session
        session["login_phone"] = "09120000000"
        session.save()
        expired = self.client.post(reverse("login_code"), {"code": "4821"})
        self.assertContains(expired, "منقضی")

        missing = self.client.post(reverse("login"), {"phone": "09120000000"})
        self.assertContains(missing, "ذخیره نشده")
        self.assertFalse(LoginCode.objects.filter(used_at__isnull=True).exists())

        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse("sms_settings")).status_code, 404)
        self.seeker.is_superuser = True
        self.seeker.save()
        saved = self.client.post(
            reverse("sms_settings"),
            {"api_key": "secret-key", "template": "login"},
        )
        self.assertRedirects(saved, reverse("sms_settings"))
        page = self.client.get(reverse("sms_settings"))
        self.assertContains(page, "-key")
        self.assertNotContains(page, "secret-key")
        self.client.logout()

        with patch("talent.sms.urllib.request.urlopen") as opened:
            body = MagicMock()
            body.read.return_value = b'{"return":{"status":200,"message":"ok"}}'
            opened.return_value.__enter__.return_value = body
            deliver_code("09120000000", "4821")
        request = opened.call_args.args[0]
        self.assertIn("/v1/secret-key/sms/send.json", request.full_url)
        self.assertIn(b"4821", request.data)
        self.assertIn("%234821".encode(), request.data)
        self.assertIn(b"85.198.54.48", request.data)

        with patch("talent.sms.urllib.request.urlopen") as opened:
            body = MagicMock()
            body.read.return_value = b'{"return":{"status":424,"message":"no"}}'
            opened.return_value.__enter__.return_value = body
            with self.assertRaises(SmsError):
                deliver_code("09120000000", "4821")
        self.assertEqual(SmsSetting.objects.get().template, "login")

    def test_staff_and_support_can_define_a_user(self):
        role = Role.objects.get(slug="laptop-repair")
        support = User.objects.create_user("support-1")
        support.is_staff = True
        support.profile.is_support = True
        support.profile.phone = "09120000077"
        support.profile.save()
        support.save()
        self.client.force_login(support)
        blocked = self.client.post(
            reverse("moderation"),
            {"kind": "create-user", "display_name": "", "phone": "091200"},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "تعریف کاربر")
        created = self.client.post(
            reverse("moderation"),
            {
                "kind": "create-user",
                "display_name": "رضا تعمیر",
                "phone": "09126667788",
                "city": "کرج",
                "roles": [role.pk],
            },
        )
        self.assertRedirects(created, reverse("moderation"))
        profile = User.objects.get(username="09126667788").profile
        self.assertEqual(profile.display_name, "رضا تعمیر")
        self.assertEqual(profile.account_status, "approved")
        self.assertEqual(profile.city, "کرج")
        self.assertTrue(
            profile.role_links.filter(role=role, status=ProfileRole.Status.APPROVED).exists()
        )
        self.assertTrue(profile.is_public())
        duplicate = self.client.post(
            reverse("moderation"),
            {"kind": "create-user", "display_name": "کس دیگر", "phone": "09126667788"},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertContains(duplicate, "قبلاً ثبت شده")
        self.client.logout()
        self.client.force_login(self.outsider)
        denied = self.client.post(
            reverse("moderation"),
            {"kind": "create-user", "display_name": "غریبه", "phone": "09129998877"},
        )
        self.assertEqual(denied.status_code, 302)
        self.assertFalse(User.objects.filter(username="09129998877").exists())

    def test_confirmed_location_is_found_near_the_searcher(self):
        self.client.force_login(self.actor)
        saved = self.client.post(
            reverse("dashboard"),
            {"form": "location", "latitude": "35.721900", "longitude": "51.334700"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertJSONEqual(saved.content, {"ok": True})
        self.actor.profile.refresh_from_db()
        self.assertEqual(float(self.actor.profile.latitude), 35.7219)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "تایید موقعیت")
        self.assertContains(page, "profile-map")
        self.assertContains(page, "ثبت شد")
        self.assertContains(page, "tnSaved")
        near = self.client.get(reverse("home"), {"lat": "35.720000", "lng": "51.330000", "radius": "5"})
        self.assertContains(near, "نگار")
        self.assertContains(near, "تایید و پیدا کن")
        far = self.client.get(reverse("home"), {"lat": "29.600000", "lng": "52.500000", "radius": "5"})
        self.assertNotContains(far, "نگار")

    def test_approved_identity_shows_vip_without_exposing_the_file(self):
        self.client.force_login(self.actor)
        image = Image.new("RGB", (24, 24), "white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        missing_title = self.client.post(
            reverse("dashboard"),
            {"form": "identity", "kind": "other", "title": "", "file": SimpleUploadedFile("x.png", buffer.getvalue(), content_type="image/png")},
        )
        self.assertEqual(missing_title.status_code, 200)
        self.assertContains(missing_title, "عنوان")
        buffer.seek(0)
        sent = self.client.post(
            reverse("dashboard"),
            {
                "form": "identity",
                "kind": "national_card",
                "title": "",
                "file": SimpleUploadedFile("card.png", buffer.getvalue(), content_type="image/png"),
            },
        )
        self.assertEqual(sent.status_code, 302)
        document = IdentityDocument.objects.get()
        self.actor.profile.refresh_from_db()
        self.assertFalse(self.actor.profile.is_vip)
        public = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertNotContains(public, ">VIP<")
        self.assertContains(public, "review-list")
        self.assertEqual(self.client.get(reverse("identity_file", args=[document.pk])).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("identity_file", args=[document.pk])).status_code, 404)
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        queue = self.client.get(reverse("moderation"))
        self.assertContains(queue, "تایید هویت")
        approved = self.client.post(
            reverse("moderation"),
            {"kind": "identity", "id": document.pk, "action": "approve", "staff_score": "4"},
        )
        self.assertEqual(approved.status_code, 302)
        self.actor.profile.refresh_from_db()
        self.assertTrue(self.actor.profile.is_vip)
        self.assertEqual(self.actor.profile.staff_score, 4)
        page = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(page, "VIP")
        self.assertContains(page, "هویت تایید شد")
        self.assertContains(page, "star-row")
        self.assertContains(page, "امتیاز مدیریت")
        self.assertContains(page, "review-compose")
        home = self.client.get(reverse("home"))
        self.assertContains(home, "VIP")
        self.assertContains(home, "هویت تایید شد")
        self.assertContains(home, 'class="on"')
        self.assertEqual(self.client.get(reverse("identity_file", args=[document.pk])).status_code, 200)
        self.client.force_login(self.actor)
        self.assertContains(self.client.get(reverse("dashboard")), "هویت تو تایید شد")

    def test_staff_sets_the_google_title_and_description_for_a_user(self):
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("system_users"), {"q": "نگار"})
        self.assertContains(page, "سئو گوگل")
        self.assertContains(page, "اگر خالی بماند")
        self.assertContains(page, "امتیاز سئو")
        self.assertContains(page, "از ۱۰۰")
        self.assertContains(page, "عنوان اختصاصی خالی است")
        self.assertContains(page, "خطایی که جلوی گوگل را بگیرد نیست")
        saved = self.client.post(
            reverse("system_users"),
            {
                "kind": "seo",
                "id": self.actor.profile.pk,
                "filter_q": "نگار",
                "seo_title": "تعمیر لپ‌تاپ در تهران | نگار",
                "seo_description": "نگار تعمیر لپ‌تاپ را در تهران انجام می‌دهد.",
            },
            follow=True,
        )
        self.assertContains(saved, "سئوی این کاربر ذخیره شد")
        self.assertContains(saved, "بهتر است حدود ۱۲۰")
        self.actor.profile.refresh_from_db()
        self.assertEqual(self.actor.profile.seo_title, "تعمیر لپ‌تاپ در تهران | نگار")
        public = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(public, "تعمیر لپ‌تاپ در تهران | نگار")
        self.assertContains(public, "نگار تعمیر لپ‌تاپ را در تهران انجام می‌دهد.")
        too_long = self.client.post(
            reverse("system_users"),
            {
                "kind": "seo",
                "id": self.actor.profile.pk,
                "filter_q": "نگار",
                "seo_title": "ن" * 80,
                "seo_description": "کوتاه",
            },
            follow=True,
        )
        self.assertContains(too_long, "حداکثر ۷۰ حرف")
        self.actor.profile.refresh_from_db()
        self.assertEqual(self.actor.profile.seo_title, "تعمیر لپ‌تاپ در تهران | نگار")
        self.actor.profile.seo_description = "تماس 09120000000 برای تعمیر"
        self.actor.profile.save(update_fields=["seo_description"])
        flagged = self.client.get(reverse("system_users"), {"q": "نگار"})
        self.assertContains(flagged, "شماره تلفن داخل عنوان یا توضیح است")

    def test_the_same_google_box_covers_sections_blog_and_fixed_pages(self):
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        laptop = Category.objects.get(slug="laptop")
        board = self.client.get(reverse("categories"))
        self.assertContains(board, "سئو گوگل")
        self.assertContains(board, "از ۱۰۰")
        self.assertContains(board, "اگر خالی بماند")
        self.assertContains(board, "عنوان اختصاصی خالی است")
        title = "تعمیر لپ‌تاپ در سراسر ایران | فیکسوگرام"
        description = "متخصص تاییدشده تعمیر لپ‌تاپ را با شهر، امتیاز و نمونه کار در فیکسوگرام پیدا کن."
        saved = self.client.post(
            reverse("categories"),
            {"form": "category_seo", "id": laptop.pk, "seo_title": title, "seo_description": description},
            follow=True,
        )
        self.assertContains(saved, "سئوی این دسته ذخیره شد")
        section = self.client.get(reverse("section", args=["laptop"]))
        self.assertContains(section, title)
        self.assertContains(section, description)
        too_long = self.client.post(
            reverse("categories"),
            {"form": "category_seo", "id": laptop.pk, "seo_title": "ن" * 80, "seo_description": "کوتاه"},
            follow=True,
        )
        self.assertContains(too_long, "حداکثر ۷۰ حرف")
        laptop.refresh_from_db()
        self.assertEqual(laptop.seo_title, title)

        news = BlogCategory.objects.create(name="آموزش تعمیر")
        write = self.client.get(reverse("blog_write"))
        self.assertContains(write, "سئو گوگل")
        blog_title = "آموزش تعمیر لپ‌تاپ | بلاگ فیکسوگرام"
        blog_text = "نوشته‌های آموزش تعمیر لپ‌تاپ، باتری و شارژر را در بلاگ فیکسوگرام بخوان."
        self.client.post(
            reverse("blog_write"),
            {
                "form": "blog_category_seo",
                "id": news.pk,
                "seo_title": blog_title,
                "seo_description": blog_text,
            },
        )
        listing = self.client.get(reverse("blog"), {"category": news.pk})
        self.assertContains(listing, blog_title)
        self.assertContains(listing, blog_text)
        self.assertContains(write, "صفحه اصلی بلاگ")
        index_title = "بلاگ فیکسوگرام | آموزش تعمیر لپ‌تاپ"
        index_text = "نوشته‌های آموزش و خبر تعمیر لپ‌تاپ و کامپیوتر را در صفحه اصلی بلاگ فیکسوگرام بخوان."
        saved_index = self.client.post(
            reverse("blog_write"),
            {"form": "page_seo", "id": "blog", "seo_title": index_title, "seo_description": index_text},
            follow=True,
        )
        self.assertContains(saved_index, "سئوی صفحه اصلی بلاگ ذخیره شد")
        blog_home = self.client.get(reverse("blog"))
        self.assertContains(blog_home, index_title)
        self.assertContains(blog_home, index_text)
        post = Post.objects.create(
            title="عمر باتری",
            category=news,
            body="<p>متن کافی برای نوشته بلاگ است.</p>",
            is_published=True,
            author=self.seeker,
        )
        draft = Post.objects.create(
            title="پیش‌نویس مخفی",
            category=news,
            body="<p>این هنوز منتشر نشده است.</p>",
            is_published=False,
            author=self.seeker,
        )
        edited = self.client.post(
            reverse("blog_edit", args=[post.pk]),
            {
                "form": "post",
                "title": post.title,
                "category": news.pk,
                "body": post.body,
                "is_published": "on",
                "seo_title": "عمر باتری لپ‌تاپ | فیکسوگرام",
                "seo_description": "چطور عمر باتری لپ‌تاپ را بیشتر کنی؛ شارژ، گرما و عادت‌هایی که باتری را خالی می‌کنند.",
            },
        )
        self.assertEqual(edited.status_code, 302)
        detail = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(detail, "عمر باتری لپ‌تاپ | فیکسوگرام")
        drafts = self.client.get(reverse("blog_edit", args=[draft.pk]))
        self.assertContains(drafts, "این نوشته پیش‌نویس است و در گوگل نمی‌آید.")
        self.assertContains(drafts, draft.title)

        phone = Category.objects.create(name="دسته شماره تست")
        self.client.post(
            reverse("categories"),
            {
                "form": "category_seo",
                "id": phone.pk,
                "seo_title": "تعمیر مانیتور در تهران | فیکسوگرام",
                "seo_description": "برای هماهنگی با 09120000000 تماس بگیر و نوبت تعمیر مانیتور بگیر.",
            },
        )
        flagged = self.client.get(reverse("categories"))
        self.assertContains(flagged, "شماره تلفن داخل عنوان یا توضیح است")

        blocked = self.client.get(reverse("desk"))
        self.assertNotContains(blocked, "سئوی صفحه‌های ثابت")
        self.seeker.is_superuser = True
        self.seeker.save()
        home_title = "فیکسوگرام | متخصص تعمیر لپ‌تاپ و کامپیوتر"
        home_text = "متخصص تاییدشده تعمیر لپ‌تاپ، کامپیوتر و آموزش را با شهر و امتیاز در فیکسوگرام پیدا کن."
        desk = self.client.post(
            reverse("desk"),
            {"form": "page_seo", "id": "home", "seo_title": home_title, "seo_description": home_text},
            follow=True,
        )
        self.assertContains(desk, "سئوی صفحه ذخیره شد")
        self.assertContains(desk, "سئوی صفحه‌های ثابت")
        home = self.client.get(reverse("home"))
        self.assertContains(home, home_title)
        self.assertContains(home, home_text)
        jobs = self.client.get(reverse("jobs"))
        self.assertContains(jobs, "استخدام و نیاز به کار")
        terms = self.client.get(reverse("terms"))
        self.assertContains(terms, "شرایط استفاده — فیکسوگرام")

    def test_public_pages_expose_search_metadata(self):
        self.actor.profile.account_status = "approved"
        self.actor.profile.headline = "تعمیر لپ‌تاپ در محل"
        self.actor.profile.save()
        profile = self.client.get(reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(profile, 'name="description"')
        self.assertContains(profile, "تعمیر لپ‌تاپ در محل")
        self.assertContains(profile, "LocalBusiness")
        self.assertContains(profile, reverse("profile", args=[self.actor.profile.pk]))
        self.assertNotContains(profile, "09120000000")
        self.assertContains(profile, 'class="crumbs"')

        filtered = self.client.get(reverse("section", args=["laptop"]), {"q": "نگار"})
        self.assertContains(filtered, "noindex,follow")
        section = self.client.get(reverse("section", args=["laptop"]))
        self.assertContains(section, "متخصص‌های تاییدشده")
        self.assertContains(section, "CollectionPage")
        self.assertContains(section, "index,follow")

        news = BlogCategory.objects.create(name="تعمیر")
        post = Post.objects.create(
            title="عمر باتری لپ‌تاپ",
            category=news,
            body="<h2>مراقبت</h2><p>شارژ را بین بیست و هشتاد نگه دار.</p><script>alert(1)</script>",
            is_published=True,
            author=self.actor,
        )
        draft = Post.objects.create(
            title="پیش‌نویس سئو",
            category=news,
            body="نباید در نقشه باشد.",
            is_published=False,
        )
        detail = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(detail, "BlogPosting")
        self.assertContains(detail, "شارژ را بین بیست و هشتاد نگه دار")
        self.assertNotContains(detail, "alert(1)")
        listing = self.client.get(reverse("blog"), {"category": news.pk})
        self.assertContains(listing, f"category={news.pk}")
        self.assertContains(listing, "index,follow")

        home = self.client.get(reverse("home"), {"q": "نگار"})
        self.assertContains(home, "noindex,follow")
        self.assertContains(home, "SearchAction")

        sitemap = self.client.get(reverse("sitemap"))
        self.assertContains(sitemap, reverse("profile", args=[self.actor.profile.pk]))
        self.assertContains(sitemap, reverse("section", args=["laptop"]))
        self.assertContains(sitemap, reverse("blog_detail", args=[post.pk]))
        self.assertNotContains(sitemap, reverse("blog_detail", args=[draft.pk]))
        self.assertNotContains(sitemap, reverse("profile", args=[self.seeker.profile.pk]))
        robots = self.client.get(reverse("robots"))
        self.assertContains(robots, "Sitemap:")
        self.assertContains(robots, "/me/")
        self.assertContains(robots, "/blog/write/")

    def test_site_can_be_installed_on_a_phone(self):
        home = self.client.get(reverse("home"))
        self.assertContains(home, reverse("manifest"))
        self.assertContains(home, "apple-touch-icon")
        self.assertContains(home, "serviceWorker.register")
        self.assertContains(home, "/app-sw.js")
        self.assertContains(home, "نصب روی گوشی")
        self.assertContains(home, "onclick=\"tnInstall()\"")
        self.assertContains(home, "event.prompt(")
        self.assertNotContains(home, "navigator.share")
        self.assertNotContains(home, "userActivation")
        self.assertNotContains(home, "اگر پنجره نصب باز نشد")
        manifest = self.client.get(reverse("manifest"))
        self.assertEqual(manifest["Content-Type"].split(";")[0], "application/manifest+json")
        payload = json.loads(manifest.content)
        self.assertEqual(payload["display"], "standalone")
        self.assertEqual(payload["name"], "فیکسوگرام")
        self.assertIn("icon-192.png", payload["icons"][0]["src"])
        self.assertIn("icon-512.png", payload["icons"][1]["src"])
        self.assertNotIn("maskable", manifest.content.decode())
        worker = self.client.get(reverse("service_worker"))
        self.assertNotIn("cookie", worker.headers.get("Vary", "").lower())
        self.assertContains(worker, 'addEventListener("fetch"')
        self.assertContains(worker, 'addEventListener("push"')
        self.assertContains(worker, "اتصال اینترنت قطع است")

    def test_staff_can_edit_and_delete_blog_categories(self):
        news = BlogCategory.objects.create(name="اخبار")
        empty = BlogCategory.objects.create(name="موقت")
        Post.objects.create(title="یک خبر", category=news, body="متن خبر", is_published=True)
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("blog_write"))
        self.assertContains(page, "ویرایش")
        self.assertContains(page, "حذف")
        renamed = self.client.post(
            reverse("blog_write"),
            {"form": "category_edit", "id": news.pk, "name": "تازه‌ها"},
        )
        self.assertRedirects(renamed, reverse("blog_write"))
        news.refresh_from_db()
        self.assertEqual(news.name, "تازه‌ها")
        blocked = self.client.post(
            reverse("blog_write"),
            {"form": "category_delete", "id": news.pk},
        )
        self.assertRedirects(blocked, reverse("blog_write"))
        self.assertTrue(BlogCategory.objects.filter(pk=news.pk).exists())
        removed = self.client.post(
            reverse("blog_write"),
            {"form": "category_delete", "id": empty.pk},
        )
        self.assertRedirects(removed, reverse("blog_write"))
        self.assertFalse(BlogCategory.objects.filter(pk=empty.pk).exists())
        listing = self.client.get(reverse("blog"))
        self.assertContains(listing, "blog-cats")
        self.assertContains(listing, "تازه‌ها")
        self.assertContains(listing, "1 نوشته")

    def test_blog_post_cover_is_resized_like_other_uploads(self):
        news = BlogCategory.objects.create(name="کاور تست")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("blog_write"))
        self.assertContains(page, "تصویر نوشته")
        self.assertContains(page, "۸۰۰ در ۴۵۰")
        buffer = BytesIO()
        Image.new("RGB", (1200, 800), (20, 90, 160)).save(buffer, format="JPEG", quality=90)
        cover = SimpleUploadedFile("wide.jpg", buffer.getvalue(), content_type="image/jpeg")
        created = self.client.post(
            reverse("blog_write"),
            {
                "form": "post",
                "title": "نوشته با کاور",
                "category": news.pk,
                "body": "<p>متن کافی برای نوشته با تصویر کاور است.</p>",
                "is_published": "on",
                "cover": cover,
            },
        )
        post = Post.objects.get(title="نوشته با کاور")
        self.assertRedirects(created, reverse("blog_detail", args=[post.pk]))
        self.assertTrue(post.cover)
        with Image.open(post.cover) as opened:
            self.assertEqual(opened.size, (800, 450))
        detail = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(detail, "post-cover")
        self.assertContains(detail, "post-head has-cover")
        listing = self.client.get(reverse("blog"))
        self.assertContains(listing, "post-thumb")
        self.assertContains(listing, "blog-cat-icon")
        edit = self.client.get(reverse("blog_edit", args=[post.pk]))
        self.assertContains(edit, "ویرایش نوشته")
        self.assertContains(edit, "۸۰۰ در ۴۵۰")
        self.assertNotContains(edit, "همه نوشته‌ها")

    def test_blog_has_two_banners_and_comments(self):
        def picture(name):
            buffer = BytesIO()
            Image.new("RGB", (40, 16), (20, 90, 160)).save(buffer, format="PNG")
            return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

        news = BlogCategory.objects.create(name="آموزش تعمیر")
        post = Post.objects.create(
            title="تمیز کردن فن",
            category=news,
            body="فن را با باد ملایم تمیز کن.",
            is_published=True,
            author=self.actor,
        )
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        for number in range(2):
            added = self.client.post(
                reverse("banners"),
                {
                    "title": f"تبلیغ بلاگ {number}",
                    "link": f"https://example.com/blog{number}",
                    "place": "blog",
                    "image": picture(f"blog{number}.png"),
                },
            )
            self.assertRedirects(added, reverse("banners"))
        blocked = self.client.post(
            reverse("banners"),
            {
                "title": "سوم",
                "link": "https://example.com/blog-extra",
                "place": "blog",
                "image": picture("extra.png"),
            },
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "بلاگ دو بنر دارد")
        self.assertEqual(Banner.objects.filter(place="blog").count(), 2)
        listing = self.client.get(reverse("blog"))
        self.assertContains(listing, "banner-pair")
        self.assertContains(listing, reverse("banner_go", args=[Banner.objects.get(link="https://example.com/blog0").pk]))

        self.client.force_login(self.outsider)
        score_only = self.client.post(reverse("blog_comment", args=[post.pk]), {"score": "4"})
        self.assertRedirects(score_only, reverse("blog_detail", args=[post.pk]))
        self.client.force_login(self.actor)
        note = self.client.post(
            reverse("blog_comment", args=[post.pk]),
            {"body": "همین روش را امتحان کردم."},
        )
        self.assertRedirects(note, reverse("blog_detail", args=[post.pk]))
        empty = self.client.post(reverse("blog_comment", args=[post.pk]), {})
        self.assertRedirects(empty, reverse("blog_detail", args=[post.pk]))
        self.assertEqual(PostComment.objects.filter(author=self.actor).count(), 1)
        page = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(page, "همین روش را امتحان کردم.")
        self.assertContains(page, "★ 4")
        self.assertContains(page, "review-compose")
        self.client.logout()
        public = self.client.get(reverse("blog_detail", args=[post.pk]))
        self.assertContains(public, "وارد شو")
        self.assertContains(public, "همین روش را امتحان کردم.")
        self.assertNotContains(public, "review-compose")

    def test_staff_can_edit_and_delete_categories_and_specialties(self):
        laptop = Category.objects.get(slug="laptop")
        repair = Role.objects.get(slug="laptop-repair")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("categories"))
        self.assertContains(page, "ویرایش")
        self.assertContains(page, "حذف")
        tree_html = page.content.decode().split("cat-tree", 1)[1].split("دسته جدید", 1)[0]
        self.assertIn("csrfmiddlewaretoken", tree_html)
        self.assertContains(page, "دسته جدید")
        self.assertNotContains(page, "تخصص داخل یک دسته")
        created = self.client.post(
            reverse("categories"),
            {"form": "new_category", "name": "نصب شبکه"},
        )
        self.assertRedirects(created, reverse("categories"))
        fresh = Category.objects.get(name="نصب شبکه")
        self.assertIsNone(fresh.parent_id)
        renamed = self.client.post(
            reverse("categories"),
            {"form": "category_edit", "id": laptop.pk, "name": "تعمیر لپ‌تاپ خانگی"},
        )
        self.assertRedirects(renamed, reverse("categories"))
        laptop.refresh_from_db()
        self.assertEqual(laptop.name, "تعمیر لپ‌تاپ خانگی")
        self.assertEqual(laptop.slug, "laptop")
        blocked = self.client.post(
            reverse("categories"),
            {"form": "category_delete", "id": Category.objects.get(slug="it").pk},
        )
        self.assertRedirects(blocked, reverse("categories"))
        self.assertTrue(Category.objects.filter(pk=laptop.pk).exists())
        self.assertTrue(Role.objects.filter(pk=repair.pk).exists())
        empty = Category.objects.create(name="دسته موقت", parent=laptop)
        removed = self.client.post(
            reverse("categories"),
            {"form": "category_delete", "id": empty.pk},
        )
        self.assertRedirects(removed, reverse("categories"))
        self.assertFalse(Category.objects.filter(pk=empty.pk).exists())

    def test_manager_creates_a_supporter_and_reads_the_activity_log(self):
        self.seeker.is_staff = True
        self.seeker.is_superuser = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        queue = self.client.get(reverse("moderation"))
        self.assertNotContains(queue, "ساخت پشتیبان")
        self.assertContains(queue, "تعریف کاربر")
        missing = self.client.post(
            reverse("supporters"),
            {"kind": "create-support", "display_name": "پشتیبان تست", "phone": "09123334455"},
        )
        self.assertContains(missing, "حداقل یک دسترسی")
        created = self.client.post(
            reverse("supporters"),
            {
                "kind": "create-support",
                "display_name": "پشتیبان تست",
                "phone": "09123334455",
                "perm": "tickets",
            },
        )
        self.assertRedirects(created, reverse("supporters"))
        helper = User.objects.get(username="09123334455")
        self.assertTrue(helper.is_staff)
        self.assertTrue(helper.profile.is_support)
        self.assertTrue(helper.profile.access.tickets)
        self.assertFalse(helper.profile.access.moderate)
        self.client.force_login(helper)
        self.assertEqual(self.client.get(reverse("supporters")).status_code, 302)
        self.assertEqual(self.client.get(reverse("support")).status_code, 200)
        self.assertEqual(self.client.get(reverse("categories")).status_code, 302)
        self.assertEqual(self.client.get(reverse("moderation")).status_code, 302)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        desk = self.client.get(reverse("desk"))
        self.assertContains(desk, "تیکت و تخلف")
        self.assertNotContains(desk, "صف تایید")
        acted = self.client.post(
            reverse("support"),
            {"kind": "ticket", "id": "1", "action": "close"},
        )
        self.assertRedirects(acted, reverse("support"))
        self.assertTrue(StaffLog.objects.filter(user=helper, summary="تیکت — بستن").exists())
        self.assertEqual(self.client.get(reverse("support_report")).status_code, 302)
        self.client.force_login(self.seeker)
        report = self.client.get(reverse("support_report"))
        self.assertContains(report, "پشتیبان تست")
        self.assertContains(report, "تیکت — بستن")
        exported = self.client.get(reverse("support_report"), {"export": "csv"})
        self.assertIn("پشتیبان تست", exported.content.decode("utf-8-sig"))
        changed = self.client.post(
            reverse("supporters"),
            {
                "kind": "edit-support",
                "id": helper.profile.pk,
                "display_name": "پشتیبان ویرایش",
                "phone": "09123334466",
                "perm": "banners",
            },
        )
        self.assertRedirects(changed, reverse("supporters"))
        helper.refresh_from_db()
        helper.profile.refresh_from_db()
        self.assertEqual(helper.username, "09123334466")
        self.assertEqual(helper.profile.display_name, "پشتیبان ویرایش")
        self.assertEqual(helper.profile.phone, "09123334466")
        self.assertTrue(helper.profile.access.banners)
        self.assertFalse(helper.profile.access.tickets)
        self.client.force_login(helper)
        self.assertEqual(self.client.get(reverse("banners")).status_code, 200)
        self.assertEqual(self.client.get(reverse("support")).status_code, 302)
        self.client.force_login(self.seeker)
        deleted = self.client.post(
            reverse("supporters"),
            {"kind": "delete-support", "id": helper.profile.pk},
        )
        self.assertRedirects(deleted, reverse("supporters"))
        self.assertFalse(User.objects.filter(pk=helper.pk).exists())

    def test_online_visitor_does_not_replace_the_admin_menu(self):
        visitor = User.objects.create_user("09125550000", password="pass12345")
        visitor.profile.phone = "09125550000"
        visitor.profile.display_name = "ویزیتور تست"
        visitor.profile.is_visitor = True
        visitor.profile.save()
        Presence.objects.create(
            session_key="visitor-online",
            user=visitor,
            path="/field/",
            last_seen=timezone.now(),
        )
        self.seeker.is_staff = True
        self.seeker.is_superuser = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "پنل")
        self.assertContains(page, "جستجو")
        self.assertContains(page, "online-pill")
        self.assertContains(page, "نفر آنلاین")
        self.assertNotContains(page, ">پذیرش<")
        desk = self.client.get(reverse("desk"))
        self.assertContains(desk, "پنل فیکسوگرام")
        self.assertContains(desk, "صف تایید")

    def test_visitor_registers_a_phone_and_manager_sees_the_count(self):
        visitor = User.objects.create_user("09123330000", password="pass12345")
        visitor.profile.phone = "09123330000"
        visitor.profile.display_name = "ویزیتور اصفهان"
        visitor.profile.is_visitor = True
        visitor.profile.city = "اصفهان"
        visitor.profile.account_status = "approved"
        visitor.profile.save()
        self.client.force_login(visitor)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("field_desk"))
        page = self.client.get(reverse("field_desk"))
        self.assertContains(page, "ثبت کاربر")
        self.assertNotContains(page, "پیام‌ها")
        role = Role.objects.get(slug="laptop-repair")
        saved = self.client.post(
            reverse("field_desk"),
            {
                "display_name": "علی رضایی",
                "phone": "09124440000",
                "instagram": "ali.repair",
                "city": "اصفهان",
                "province": "اصفهان",
                "categories": [str(role.category_id)],
            },
        )
        self.assertRedirects(saved, reverse("field_desk"))
        recruit = User.objects.get(username="09124440000").profile
        self.assertEqual(recruit.account_status, "pending")
        self.assertEqual(recruit.display_name, "علی رضایی")
        self.assertEqual(recruit.instagram, "ali.repair")
        self.assertEqual(recruit.recruited_by, visitor.profile)
        self.assertTrue(recruit.role_links.filter(role__category_id=role.category_id, status="pending").exists())
        duplicate = self.client.post(
            reverse("field_desk"),
            {"display_name": "کس دیگر", "phone": "09120000000", "roles": [str(role.pk)]},
        )
        self.assertContains(duplicate, "قبلاً ثبت شده")
        desk = self.client.get(reverse("field_desk"))
        self.assertContains(desk, "کار امروز")
        self.assertContains(desk, "علی رضایی")
        self.assertContains(desk, "ثبت فایل")
        self.assertContains(desk, "1")
        image = Image.new("RGB", (8, 8), "white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        uploaded = self.client.post(
            reverse("field_desk"),
            {
                "kind": "visit-file",
                "id": recruit.pk,
                "file": SimpleUploadedFile("visit.png", buffer.getvalue(), content_type="image/png"),
            },
        )
        self.assertRedirects(uploaded, reverse("field_desk"))
        recruit.refresh_from_db()
        self.assertTrue(recruit.visit_file)
        opened = self.client.get(reverse("visit_file", args=[recruit.pk]))
        self.assertEqual(opened.status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("visit_file", args=[recruit.pk])).status_code, 404)
        self.client.force_login(visitor)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse("field_desk")).status_code, 404)
        manager = User.objects.create_superuser("manager-visit", "visit@example.com", "pass12345")
        self.client.force_login(manager)
        report = self.client.get(reverse("visitors"))
        self.assertContains(report, "ویزیتور اصفهان")
        self.assertContains(report, "09124440000")
        self.assertContains(report, "علی رضایی")
        self.assertContains(report, "کل 1")
        self.assertContains(report, "جستجو")
        self.assertContains(report, "ویرایش")
        self.assertContains(report, "غیرفعال")
        self.assertContains(report, "توضیحات")
        found = self.client.get(reverse("visitors"), {"name": "اصفهان", "city": "اصفهان"})
        self.assertContains(found, "ویزیتور اصفهان")
        missed = self.client.get(reverse("visitors"), {"city": "یزد"})
        self.assertContains(missed, "پیدا نشد")
        self.assertContains(missed, "0 از 1")
        self.assertNotContains(missed, "09123330000")
        queue = self.client.get(reverse("moderation"))
        self.assertContains(queue, "ویزیتور: ویزیتور اصفهان")
        early = self.client.post(
            reverse("visitors"),
            {"kind": "settle", "id": visitor.profile.pk, "amount": "100", "note": "زود"},
        )
        self.assertRedirects(early, reverse("visitors"))
        self.assertFalse(visitor.profile.settlements.exists())
        recruit.account_status = "approved"
        recruit.save(update_fields=["account_status"])
        settled = self.client.post(
            reverse("visitors"),
            {"kind": "settle", "id": visitor.profile.pk, "amount": "200000", "note": "تسویه هفته"},
        )
        self.assertRedirects(settled, reverse("visitors"))
        recruit.refresh_from_db()
        self.assertIsNotNone(recruit.settlement_id)
        self.client.force_login(visitor)
        cart = self.client.get(reverse("field_desk"))
        self.assertContains(cart, "تسویه هفته")
        self.assertContains(cart, "200000")
        self.client.force_login(manager)
        edited = self.client.post(
            reverse("visitors"),
            {
                "kind": "save-specs",
                "id": visitor.profile.pk,
                "display_name": "ویزیتور اصفهان",
                "phone": "09123330000",
                "city": "اصفهان",
                "about": "پوشش مرکز شهر",
            },
        )
        self.assertRedirects(edited, reverse("visitors"))
        visitor.profile.refresh_from_db()
        self.assertEqual(visitor.profile.bio, "پوشش مرکز شهر")
        closed = self.client.post(
            reverse("visitors"),
            {"kind": "close-visitor", "id": visitor.profile.pk},
            follow=True,
        )
        self.assertContains(closed, "غیرفعال شد")
        visitor.profile.refresh_from_db()
        self.assertFalse(visitor.profile.is_visitor)
        self.client.force_login(visitor)
        self.assertEqual(self.client.get(reverse("field_desk")).status_code, 404)

    def test_specialties_are_listed_and_the_approval_queue_names_them(self):
        self.client.force_login(self.actor)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, 'class="role-board"')
        self.assertContains(page, "تعمیر لپ‌تاپ")
        self.assertContains(page, "ذخیره تخصص‌ها")
        role = Role.objects.get(slug="laptop-repair")
        other = Role.objects.get(slug="printer")
        link, _created = ProfileRole.objects.update_or_create(
            profile=self.actor.profile,
            role=role,
            defaults={"status": ProfileRole.Status.PENDING},
        )
        second, _created = ProfileRole.objects.update_or_create(
            profile=self.actor.profile,
            role=other,
            defaults={"status": ProfileRole.Status.PENDING},
        )
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        queue = self.client.get(reverse("moderation"))
        self.assertContains(queue, "مورد منتظر تایید")
        self.assertContains(queue, "نگار: تعمیر لپ‌تاپ، تعمیر پرینتر")
        self.assertContains(queue, "تایید همه")
        self.assertContains(queue, "جزئیات")
        self.assertNotContains(queue, "می‌خواهد «تعمیر لپ‌تاپ»")
        one = self.client.post(
            reverse("moderation"),
            {"kind": "role", "id": link.pk, "action": "reject"},
        )
        self.assertRedirects(one, reverse("moderation"))
        link.refresh_from_db()
        self.assertEqual(link.status, ProfileRole.Status.REJECTED)
        approved = self.client.post(
            reverse("moderation"),
            {"kind": "role-user", "id": self.actor.profile.pk, "action": "approve"},
        )
        self.assertRedirects(approved, reverse("moderation"))
        second.refresh_from_db()
        link.refresh_from_db()
        self.assertEqual(second.status, ProfileRole.Status.APPROVED)
        self.assertEqual(link.status, ProfileRole.Status.REJECTED)

    def test_visitor_and_user_can_pick_a_specialty_and_its_subcategories(self):
        parent = Category.objects.create(name="تعمیرات برد", slug="board-root")
        child = Category.objects.create(name="برد پکیج", slug="board-pack", parent=parent)
        self.assertFalse(Role.objects.filter(category=parent).exists())
        visitor = User.objects.create_user("09125550000", password="pass12345")
        visitor.profile.is_visitor = True
        visitor.profile.account_status = "approved"
        visitor.profile.phone = "09125550000"
        visitor.profile.save()
        self.client.force_login(visitor)
        page = self.client.get(reverse("field_desk"))
        self.assertContains(page, "تعمیرات برد")
        self.assertContains(page, "برد پکیج")
        self.assertContains(page, 'name="categories"')
        self.assertNotContains(page, "data-role-groups")
        saved = self.client.post(
            reverse("field_desk"),
            {
                "display_name": "مهدی برد",
                "phone": "09126660011",
                "categories": [str(parent.pk), str(child.pk)],
            },
        )
        self.assertRedirects(saved, reverse("field_desk"))
        recruit = User.objects.get(username="09126660011").profile
        self.assertEqual(
            set(recruit.role_links.values_list("role__category_id", flat=True)),
            {parent.pk, child.pk},
        )
        self.client.force_login(self.actor)
        desk = self.client.get(reverse("dashboard"))
        self.assertContains(desk, "برد پکیج")
        self.assertContains(desk, 'name="categories"')
        kept = self.client.post(
            reverse("dashboard"),
            {"form": "roles", "categories": [str(child.pk)]},
        )
        self.assertRedirects(kept, reverse("dashboard"))
        chosen = set(self.actor.profile.role_links.values_list("role__category_id", flat=True))
        self.assertIn(child.pk, chosen)
        self.assertNotIn(parent.pk, chosen)
        self.assertNotIn(Role.objects.get(slug="laptop-repair").category_id, chosen)

    def test_the_manager_can_rewrite_homepage_sentences(self):
        home = self.client.get(reverse("home"))
        self.assertContains(home, "فیکسوگرام جای پیدا کردن")
        self.assertContains(home, "متخصص تعمیر لپ‌تاپ")
        self.seeker.is_staff = True
        self.seeker.save()
        self.client.force_login(self.seeker)
        blocked = self.client.get(reverse("desk"))
        self.assertNotContains(blocked, "نوشته‌های صفحه اصلی")
        self.seeker.is_superuser = True
        self.seeker.save()
        desk = self.client.get(reverse("desk"))
        self.assertContains(desk, "نوشته‌های صفحه اصلی")
        self.assertContains(desk, "فیکسوگرام جای پیدا کردن")
        saved = self.client.post(
            reverse("desk"),
            {
                "form": "home_copy",
                "eyebrow": "تعمیر و آموزش",
                "headline": "عنوان تازه صفحه",
                "lead": "توضیح تازه زیر عنوان",
                "section_link": "دیدن متخصص‌های این بخش",
                "empty_people": "هنوز متخصص تاییدشده‌ای در فهرست نیست.",
                "jobs_title": "استخدام و نیاز به کار",
                "jobs_lead": "توضیح تازه استخدام",
                "empty_jobs": "هنوز آگهی تاییدشده‌ای نیست.",
                "jobs_button": "دیدن آگهی‌ها و ثبت آگهی",
                "footer": "متن تازه پایین صفحه",
            },
        )
        self.assertRedirects(saved, reverse("desk"))
        page = self.client.get(reverse("home"))
        self.assertContains(page, "عنوان تازه صفحه")
        self.assertContains(page, "توضیح تازه زیر عنوان")
        self.assertContains(page, "توضیح تازه استخدام")
        self.assertContains(page, "متن تازه پایین صفحه")
        self.assertContains(page, "<h1>عنوان تازه صفحه</h1>")

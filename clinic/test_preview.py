from django.test import SimpleTestCase, RequestFactory
from django.http import HttpResponse

from .preview_middleware import VisitorOnlyMiddleware


class PreviewTests(SimpleTestCase):
    def test_admin_and_unknown_routes_never_reach_app(self):
        def forbidden(request):
            self.fail("Protected route reached application")
        middleware = VisitorOnlyMiddleware(forbidden)
        for path in ["/admin/", "/admin/login/", "/manager/dashboard/", "/manager/team/", "/db.sqlite3"]:
            self.assertEqual(middleware(RequestFactory().get(path)).status_code, 404)

    def test_visitor_page_allows_telegram_embedding(self):
        def visitor(request):
            response = HttpResponse("Клиника")
            response["X-Frame-Options"] = "DENY"
            return response
        response = VisitorOnlyMiddleware(visitor)(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Frame-Options", response)
        self.assertIn("https://web.telegram.org", response["Content-Security-Policy"])

    def test_account_pages_are_available_in_preview(self):
        middleware = VisitorOnlyMiddleware(lambda request: HttpResponse("ok"))
        for path in ("/register/", "/login/", "/cabinet/", "/api/doctors/1/slots/"):
            self.assertEqual(middleware(RequestFactory().get(path)).status_code, 200)

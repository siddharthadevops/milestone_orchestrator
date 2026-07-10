"""Authentication policy and project-membership tests."""

import unittest

from orchestrator import access


class AccessTest(unittest.TestCase):
    def test_local_loopback_is_admin(self):
        who = access.identity({"Host": "127.0.0.1:8700"})
        self.assertEqual(who["email"], access.ADMIN_EMAIL)
        self.assertTrue(who["admin"])
        self.assertTrue(who["local"])

    def test_public_host_without_oauth_marker_fails_closed(self):
        with self.assertRaises(access.AccessDenied):
            access.identity({"Host": "example.ngrok-free.dev"})

    def test_remote_known_user_is_not_admin(self):
        who = access.identity({
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: access.USER_EMAILS[0].upper(),
        })
        self.assertEqual(who["email"], access.USER_EMAILS[0])
        self.assertFalse(who["admin"])
        self.assertFalse(who["local"])

    def test_remote_unknown_user_and_spoofed_marker_are_denied(self):
        for marker, email in (
            (access.REMOTE_MARKER, "stranger@example.com"),
            ("spoofed", access.ADMIN_EMAIL),
        ):
            with self.subTest(marker=marker, email=email):
                with self.assertRaises(access.AccessDenied):
                    access.identity({
                        "Host": "example.ngrok-free.dev",
                        access.REMOTE_HEADER: marker,
                        access.USER_HEADER: email,
                    })

    def test_project_membership_is_explicit_and_admin_is_implicit(self):
        project = {"slug": "p", "users": [access.USER_EMAILS[1]]}
        admin = {"email": access.ADMIN_EMAIL, "admin": True}
        member = {"email": access.USER_EMAILS[1], "admin": False}
        outsider = {"email": access.USER_EMAILS[0], "admin": False}
        self.assertTrue(access.can_access_project(admin, project))
        self.assertTrue(access.can_access_project(member, project))
        self.assertFalse(access.can_access_project(outsider, project))

    def test_user_list_is_canonical_and_closed(self):
        self.assertEqual(
            access.validated_users([access.USER_EMAILS[1]]),
            [access.USER_EMAILS[1]],
        )
        for bad in (
            "not-a-list",
            [access.ADMIN_EMAIL],
            ["unknown@example.com"],
            [access.USER_EMAILS[0], access.USER_EMAILS[0]],
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    access.validated_users(bad)

    def test_generated_policy_authenticates_allowlist_and_replaces_headers(self):
        rules = access.ngrok_policy()["on_http_request"]
        self.assertEqual(len(rules), 4)
        removed = rules[0]["actions"][0]
        self.assertEqual(removed["type"], "remove-headers")
        self.assertEqual(
            set(removed["config"]["headers"]),
            {access.USER_HEADER, access.REMOTE_HEADER},
        )
        self.assertEqual(rules[1]["actions"][0]["type"], "oauth")
        expression = rules[2]["expressions"][0]
        for email in access.ALL_EMAILS:
            self.assertIn(email, expression)
        added = rules[3]["actions"][0]["config"]["headers"]
        self.assertEqual(added[access.REMOTE_HEADER], access.REMOTE_MARKER)
        self.assertIn("oauth.identity.email", added[access.USER_HEADER])


if __name__ == "__main__":
    unittest.main()

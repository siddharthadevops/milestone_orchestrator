"""Small, explicit access policy for the remote operator panel.

Local loopback use remains the trusted administrator path. Remote traffic
must arrive through the ngrok Google OAuth policy, which removes spoofable
identity headers and injects the authenticated email plus a marker.
"""

import json
import sys


ADMIN_EMAIL = "femistokli@gmail.com"
USER_EMAILS = (
    "isabelmariaandresruiz@gmail.com",
    "jdcf1710@gmail.com",
    "ryoandruiz@gmail.com",
)
ALL_EMAILS = (ADMIN_EMAIL,) + USER_EMAILS

USER_HEADER = "X-Orchestrator-User"
REMOTE_HEADER = "X-Orchestrator-Remote"
REMOTE_MARKER = "google-oauth"


class AccessDenied(ValueError):
    pass


def normalize_email(value):
    return str(value or "").strip().lower()


def _loopback_host(value):
    host = str(value or "").strip().lower()
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.split(":", 1)[0]
    return host in ("127.0.0.1", "localhost", "[::1]")


def identity(headers):
    """Return the authenticated request identity.

    A header-less request is administrative only on a literal loopback Host.
    Any public-host request must carry the marker and known email injected by
    the generated ngrok policy. This fails closed if OAuth/header injection is
    accidentally removed from the remote launcher.
    """
    host = headers.get("Host")
    marker = str(headers.get(REMOTE_HEADER) or "").strip().lower()
    email = normalize_email(headers.get(USER_HEADER))
    if marker:
        if marker != REMOTE_MARKER or email not in ALL_EMAILS:
            raise AccessDenied("forbidden")
        return {"email": email, "admin": email == ADMIN_EMAIL, "local": False}
    if _loopback_host(host) and not email:
        return {"email": ADMIN_EMAIL, "admin": True, "local": True}
    raise AccessDenied("forbidden")


def project_users(project):
    configured = {
        normalize_email(email) for email in (project.get("users") or [])
    }
    return [email for email in USER_EMAILS if email in configured]


def can_access_project(who, project):
    return bool(who.get("admin") or who.get("email") in project_users(project))


def project_admins(project):
    configured = {
        normalize_email(email) for email in (project.get("admins") or [])
    }
    return [email for email in USER_EMAILS if email in configured]


def can_administer_project(who, project):
    """Whether the caller may run a project's privileged operations.

    The middle rung the two-state model lacked: membership grants ordinary
    project work, this grants the operations that can damage the work area
    itself. The service administrator holds it everywhere by definition.
    """
    return bool(
        who.get("admin") or who.get("email") in project_admins(project)
    )


def validated_users(value, label="users"):
    if not isinstance(value, list):
        raise ValueError("%s must be a list" % label)
    normalized = [normalize_email(email) for email in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError("%s contains duplicates" % label)
    if any(email not in USER_EMAILS for email in normalized):
        raise ValueError(
            "%s contains an unknown or administrative email" % label
        )
    return [email for email in USER_EMAILS if email in normalized]


def validated_project_admins(value, users):
    """Project admins, which must be members: a privileged email that
    cannot even see the project would be a rung with nothing under it."""
    admins = validated_users(value, label="admins")
    member = set(users or [])
    outside = [email for email in admins if email not in member]
    if outside:
        raise ValueError("admins must be project users: %s" % outside[0])
    return admins


def ngrok_policy():
    allowed = ", ".join("'%s'" % email for email in ALL_EMAILS)
    return {
        "on_http_request": [
            {
                "actions": [
                    {
                        "type": "remove-headers",
                        "config": {"headers": [USER_HEADER, REMOTE_HEADER]},
                    }
                ]
            },
            {
                "actions": [
                    {"type": "oauth", "config": {"provider": "google"}}
                ]
            },
            {
                "expressions": [
                    "!(actions.ngrok.oauth.identity.email in [%s])" % allowed
                ],
                "actions": [{"type": "deny"}],
            },
            {
                "actions": [
                    {
                        "type": "add-headers",
                        "config": {
                            "headers": {
                                USER_HEADER: (
                                    "${actions.ngrok.oauth.identity.email}"
                                ),
                                REMOTE_HEADER: REMOTE_MARKER,
                            }
                        },
                    }
                ]
            },
        ]
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    text = json.dumps(ngrok_policy(), indent=2) + "\n"
    if argv:
        with open(argv[0], "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

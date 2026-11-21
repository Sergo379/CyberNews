"""REST and persistence checks against the disposable Stage 2 Compose project."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import uuid4

import httpx
import jwt
import pytest

AUTH = "/api/v1/auth"
MODERATION = "/api/v1/moderation"
ROLE_REASON = "Test administrative assignment"


def expect(response, status):
    assert response.status_code == status, (
        f"{response.request.method} {response.request.url.path} returned "
        f"{response.status_code}, expected {status}"
    )
    return response.json() if response.content and status < 300 else None


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=os.environ["CYBERNEWS_TEST_BASE_URL"], trust_env=False, timeout=12) as connection:
        yield connection


def compose(*args, data=None):
    project = os.environ["CYBERNEWS_TEST_PROJECT"]
    assert project.startswith("cybernews-stage2-")
    result = subprocess.run(
        [os.environ.get("CYBERNEWS_TEST_DOCKER", "docker"), "compose", "-f", "compose.yaml",
         "-f", "tests/stage2.compose.yaml", "-p", project, *args],
        input=json.dumps(data) if data is not None else None, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"Isolated Compose {args[0]} failed"
    return result.stdout


def new_data():
    suffix = uuid4().hex[:12]
    return {"email": f"test-{suffix}@example.com", "nickname": f"test-{suffix}", "password": token_urlsafe(24)}


def register(client):
    data = new_data()
    account = expect(client.post(f"{AUTH}/register", json=data), 201)
    return data, account


def login(client, data):
    body = {"email": data["email"], "password": data["password"]}
    payload = expect(client.post(f"{AUTH}/login", json=body), 200)
    assert 0 < payload["expires_in"] <= 1800
    return {"Authorization": f"Bearer {payload['access_token']}"}


def unlock(client, headers, password):
    payload = expect(client.post(f"{AUTH}/admin/unlock", headers=headers, json={"admin_password": password}), 200)
    expiry = datetime.fromisoformat(payload["expires_at"])
    assert 0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 900
    return {**headers, "X-Admin-Session": payload["admin_session"]}


def role(client, super_admin, account_id, value):
    return client.patch(
        f"{AUTH}/admin/users/{account_id}/role", headers=super_admin,
        json={"role": value, "reason": ROLE_REASON},
    )


def set_admin_password(client, headers, password, admin_password):
    return client.put(
        f"{AUTH}/admin/password", headers=headers,
        json={"current_password": password, "admin_password": admin_password},
    )


@pytest.fixture(scope="session")
def super_admin(client):
    access = login(client, {
        "email": os.environ["CYBERNEWS_TEST_SUPER_EMAIL"],
        "password": os.environ["CYBERNEWS_TEST_SUPER_PASSWORD"],
    })
    return unlock(client, access, os.environ["CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"])


@pytest.fixture
def member(client):
    data, account = register(client)
    return data, account, login(client, data)


@pytest.fixture
def moderator(client, super_admin):
    return moderator_factory(client, super_admin)


def restriction(client, headers, account_id):
    return client.post(f"{MODERATION}/restrictions", headers=headers, json={"user_id": account_id, "reason": "Policy"})


def lift(client, headers, restriction_id):
    return client.post(f"{MODERATION}/restrictions/{restriction_id}/lift", headers=headers, json={"reason": "Reviewed"})


def report(client, headers, target_type="article", target_id=None, **extra):
    return client.post(f"{MODERATION}/reports", headers=headers, json={
        "target_type": target_type, "target_id": target_id or str(uuid4()), "reason": "Review needed", **extra,
    })


def test_registration(client):
    data, account = register(client)
    assert account["role"] == "user" and account["status"] == "active"
    assert account["email"] == data["email"]
    assert set(account) == {"id", "role", "status", "email", "nickname", "created_at", "updated_at", "last_login_at"}


@pytest.mark.parametrize("field", ["email", "nickname"])
def test_unique_registration_case_insensitive(client, field):
    original, _ = register(client)
    duplicate = new_data()
    duplicate[field] = original[field].upper()
    expect(client.post(f"{AUTH}/register", json=duplicate), 409)


@pytest.mark.parametrize("fields", [
    {"email": "invalid"}, {"nickname": "ab"}, {"nickname": "x" * 33}, {"password": "short"},
    {"role": "moderator"}, {"role": "super_admin"}, {"status": "active"},
])
def test_registration_validation_and_role_injection(client, fields):
    expect(client.post(f"{AUTH}/register", json={**new_data(), **fields}), 422)


def test_login_and_profile(client, member):
    data, account, headers = member
    profile = expect(client.get(f"{AUTH}/me", headers=headers), 200)
    assert profile["id"] == account["id"] and profile["last_login_at"]
    expect(client.post(f"{AUTH}/login", json={"email": data["email"], "password": token_urlsafe(24)}), 401)
    expect(client.get(f"{AUTH}/me"), 401)


def test_profile_patch_and_password_change(client, member):
    data, account, headers = member
    profile = expect(client.patch(f"{AUTH}/me", headers=headers, json={"nickname": "updated-" + uuid4().hex[:12]}), 200)
    assert profile["id"] == account["id"] and profile["nickname"] != account["nickname"]
    expect(client.patch(f"{AUTH}/me", headers=headers, json={"role": "super_admin"}), 422)
    password = token_urlsafe(24)
    expect(client.post(f"{AUTH}/change-password", headers=headers, json={
        "current_password": token_urlsafe(24), "new_password": password,
    }), 401)
    expect(client.post(f"{AUTH}/change-password", headers=headers, json={
        "current_password": data["password"], "new_password": password,
    }), 204)
    expect(client.get(f"{AUTH}/me", headers=headers), 401)
    expect(client.get(f"{AUTH}/me", headers=login(client, {**data, "password": password})), 200)


@pytest.mark.parametrize("variant", ["expired", "wrong-signing-key", "wrong-audience", "wrong-type"])
def test_rejects_invalid_jwt(client, member, variant):
    _, account, _ = member
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"sub": account["id"], "iat": now - 120, "exp": now + 60, "iss": "cybernews-auth",
              "aud": "cybernews-api", "jti": str(uuid4()), "type": "access", "ver": 1}
    signing_key = os.environ["JWT_SECRET"]
    if variant == "expired":
        claims["exp"] = now - 60
    elif variant == "wrong-signing-key":
        signing_key = token_urlsafe(32)
    elif variant == "wrong-audience":
        claims["aud"] = "another-service"
    else:
        claims["type"] = "another-token"
    invalid = jwt.encode(claims, signing_key, algorithm="HS256")
    expect(client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {invalid}"}), 401)


def test_password_hashes_and_session_digest(super_admin, client):
    code = """import json,sys
from app.config import settings
from app.models import AdminSession, User
from app.passwords import verify_password
from cybernews_runtime.database import Database
from sqlalchemy import select
from hashlib import sha256
data=json.load(sys.stdin)
with Database(settings.database_url).sessions() as db:
    user=db.scalar(select(User).where(User.email==data['email']))
    assert user.password_hash.startswith('$argon2id$')
    assert user.admin_password_hash.startswith('$argon2id$')
    assert verify_password(data['password'],user.password_hash)
    assert verify_password(data['admin_password'],user.admin_password_hash)
    assert not verify_password(data['password'],user.admin_password_hash)
    match=db.get(AdminSession,sha256(data['session'].encode()).hexdigest())
    assert match.user_id==user.id and match.token_hash!=data['session']
"""
    compose("exec", "-T", "auth", "python", "-c", code, data={
        "email": os.environ["CYBERNEWS_TEST_SUPER_EMAIL"],
        "password": os.environ["CYBERNEWS_TEST_SUPER_PASSWORD"],
        "admin_password": os.environ["CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"],
        "session": super_admin["X-Admin-Session"],
    })
    expect(client.get(f"{AUTH}/admin/session", headers=super_admin), 200)


def test_initial_admin_bootstrap_is_one_time():
    compose("exec", "-T", "auth", "python", "-c", """import json,sys
from app.bootstrap import BootstrapError, Registration, create_first_admin
from app.config import settings
from app.models import User
from cybernews_runtime.database import Database
from sqlalchemy import func, select
data=json.load(sys.stdin)
try:
    create_first_admin(Registration(**data['registration']), data['admin_password'])
except BootstrapError:
    pass
else:
    raise AssertionError('Second initial bootstrap was allowed')
with Database(settings.database_url).sessions() as db:
    assert db.scalar(select(func.count()).select_from(User).where(User.role=='super_admin'))==1
""", data={"registration": new_data(), "admin_password": token_urlsafe(24)})


def test_admin_setup_lock_and_binding(client, super_admin):
    data, account = register(client)
    expect(role(client, super_admin, account["id"], "moderator"), 200)
    access = login(client, data)
    expect(client.get(f"{AUTH}/admin/session", headers=access), 403)
    expect(set_admin_password(client, access, data["password"], data["password"]), 400)
    expect(set_admin_password(client, access, token_urlsafe(24), token_urlsafe(24)), 401)
    password = token_urlsafe(24)
    expect(set_admin_password(client, access, data["password"], password), 204)
    expect(client.post(f"{AUTH}/admin/unlock", headers=access, json={"admin_password": data["password"]}), 403)
    admin = unlock(client, access, password)
    other_login = login(client, data)
    expect(client.get(f"{AUTH}/admin/session", headers={**other_login, "X-Admin-Session": admin["X-Admin-Session"]}), 403)
    expect(client.post(f"{AUTH}/admin/lock", headers=admin), 204)
    expect(client.get(f"{AUTH}/admin/session", headers=admin), 403)


def test_admin_session_expiration_and_password_rotation(client, moderator):
    data, _, admin = moderator
    compose("exec", "-T", "auth", "python", "-c", """import json,sys
from datetime import timedelta
from app.accounts import session_hash
from app.config import settings
from app.models import AdminSession
from cybernews_runtime.database import Database
from cybernews_runtime.security import utc_now
with Database(settings.database_url).sessions.begin() as db:
    session=db.get(AdminSession,session_hash(json.load(sys.stdin)))
    session.expires_at=utc_now()-timedelta(seconds=1)
""", data=admin["X-Admin-Session"])
    expect(client.get(f"{AUTH}/admin/session", headers=admin), 403)
    first_password = token_urlsafe(24)
    expect(set_admin_password(client, admin, data["password"], first_password), 204)
    renewed = unlock(client, admin, first_password)
    expect(set_admin_password(client, renewed, data["password"], token_urlsafe(24)), 204)
    expect(client.get(f"{AUTH}/admin/session", headers=renewed), 403)


def test_role_boundaries_and_revocation(client, member, moderator, super_admin):
    _, ordinary, member_headers = member
    _, mod, moderator_headers = moderator
    expect(role(client, moderator_headers, ordinary["id"], "moderator"), 403)
    expect(client.get(f"{AUTH}/admin/users", headers=moderator_headers), 403)
    expect(client.get(f"{AUTH}/admin/users", headers=super_admin), 200)
    expect(client.get(f"{AUTH}/admin/users", headers={**member_headers, "X-User-Role": "super_admin"}), 403)
    expect(client.post(f"{AUTH}/admin/unlock", headers=member_headers, json={"admin_password": token_urlsafe(24)}), 403)
    principal = expect(client.get(f"{AUTH}/me", headers=super_admin), 200)
    expect(role(client, super_admin, principal["id"], "user"), 403)
    expect(role(client, super_admin, principal["id"], "super_admin"), 403)
    expect(client.post(f"{AUTH}/admin/users/{principal['id']}/suspend", headers=super_admin,
                       json={"reason": "Test"}), 403)
    expect(role(client, super_admin, mod["id"], "user"), 200)
    expect(client.get(f"{AUTH}/admin/session", headers=moderator_headers), 401)
    expect(client.get(f"{MODERATION}/reports", headers=moderator_headers), 401)


def test_super_admin_can_grant_and_revoke_a_second_super_admin(client, super_admin):
    data, account = register(client)
    promoted = expect(role(client, super_admin, account["id"], "super_admin"), 200)
    assert promoted["role"] == "super_admin"
    headers = login(client, data)
    password = token_urlsafe(24)
    expect(set_admin_password(client, headers, data["password"], password), 204)
    second = unlock(client, headers, password)
    expect(client.get(f"{AUTH}/admin/users", headers=second), 200)
    demoted = expect(role(client, super_admin, account["id"], "moderator"), 200)
    assert demoted["role"] == "moderator"
    expect(client.get(f"{AUTH}/admin/session", headers=second), 401)
    expect(client.get(f"{AUTH}/admin/users", headers=super_admin), 200)


def test_restriction_permissions_and_history(client, member, moderator, super_admin):
    _, user, member_headers = member
    _, mod, admin = moderator
    expect(restriction(client, admin, mod["id"]), 403)
    expect(restriction(client, member_headers, user["id"]), 403)
    blocked = expect(restriction(client, admin, user["id"]), 201)
    expect(restriction(client, admin, user["id"]), 409)
    permission = expect(client.get(f"{MODERATION}/comment-permission", headers=member_headers), 200)
    assert permission["allowed"] is False and permission["reason"] == "comment_restricted"
    expect(lift(client, admin, blocked["id"]), 403)
    _, _, second_admin = moderator_factory(client, super_admin)
    expect(lift(client, second_admin, blocked["id"]), 403)
    lifted = expect(lift(client, super_admin, blocked["id"]), 200)
    assert lifted["lifted_at"] and lifted["lifted_by"] and not lifted["active"]
    history = expect(client.get(f"{MODERATION}/users/{user['id']}/restrictions", headers=admin), 200)
    assert history[0]["id"] == blocked["id"] and history[0]["active"] is False
    assert expect(client.get(f"{MODERATION}/comment-permission", headers=member_headers), 200)["allowed"]
    expect(lift(client, super_admin, blocked["id"]), 409)


def moderator_factory(client, super_admin):
    data, account = register(client)
    expect(role(client, super_admin, account["id"], "moderator"), 200)
    headers = login(client, data)
    admin_password = token_urlsafe(24)
    expect(set_admin_password(client, headers, data["password"], admin_password), 204)
    return data, account, unlock(client, headers, admin_password)


def test_duplicate_active_restriction_is_concurrency_safe(client, member, moderator):
    _, user, _ = member
    _, _, headers = moderator
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: restriction(client, headers, user["id"]).status_code, range(2)))
    assert sorted(statuses) == [201, 409]


def test_suspend_restore_invalidates_existing_access(client, member, moderator, super_admin):
    data, account, access = member
    _, _, mod = moderator
    url = f"{AUTH}/admin/users/{account['id']}"
    expect(client.post(f"{url}/suspend", headers=mod, json={"reason": "Policy"}), 403)
    expect(client.post(f"{url}/suspend", headers=super_admin, json={"reason": "Policy"}), 200)
    expect(client.get(f"{AUTH}/me", headers=access), 401)
    expect(report(client, access), 401)
    expect(client.post(f"{AUTH}/login", json={"email": data["email"], "password": data["password"]}), 401)
    restored = expect(client.post(f"{url}/restore", headers=super_admin, json={"reason": "Reviewed"}), 200)
    assert restored["role"] == "user" and restored["status"] == "active"
    expect(client.get(f"{AUTH}/me", headers=access), 401)
    expect(client.get(f"{AUTH}/me", headers=login(client, data)), 200)
    audit = expect(client.get(f"{AUTH}/admin/audit", headers=super_admin), 200)
    actions = {event["action"] for event in audit if event["target_id"] == account["id"]}
    assert {"account_suspended", "account_restored"} <= actions


@pytest.mark.parametrize(("target_type", "status"), [("article", "reviewed"), ("comment", "rejected"), ("user", "reviewed")])
def test_reports(client, member, moderator, super_admin, target_type, status):
    _, account, member_headers = member
    _, mod, admin = moderator
    target = account["id"]
    if target_type in {"article", "comment"}:
        article = expect(client.post("/api/v1/articles/admin/articles", headers=super_admin, json={
            "title": "Stage 2 report target", "content": "<p>Isolated report fixture.</p>", "status": "published",
        }), 201)
        target = article["id"]
        if target_type == "comment":
            comment = expect(client.post(
                f"/api/v1/community/articles/{target}/comments", headers=member_headers,
                json={"body": "Stage 2 comment fixture"},
            ), 201)
            target = comment["id"]
    expect(report(client, member_headers, target_type, target, status="reviewed"), 422)
    item = expect(report(client, member_headers, target_type, target, description="details"), 201)
    assert item["status"] == "pending" and item["author_id"] == account["id"]
    expect(client.get(f"{MODERATION}/reports", headers=member_headers), 403)
    expect(client.get(f"{MODERATION}/reports", headers=admin), 200)
    url = f"{MODERATION}/reports/{item['id']}"
    expect(client.get(url, headers=admin), 200)
    expect(client.patch(url, headers=member_headers, json={"status": status}), 403)
    changed = expect(client.patch(url, headers=admin, json={"status": status}), 200)
    assert changed["status"] == status and changed["reviewed_by"] == mod["id"]
    expect(client.patch(url, headers=admin, json={"status": status}), 409)
    audit = expect(client.get(f"{MODERATION}/admin/audit", headers=admin), 200)
    assert any(event["target_id"] == item["id"] and event["action"] == f"report_{status}" for event in audit)


def test_rate_limits_login_and_admin_unlock(client, moderator):
    data = new_data()
    expect(client.post(f"{AUTH}/register", json=data), 201)
    invalid = {"email": data["email"], "password": token_urlsafe(24)}
    for _ in range(5):
        expect(client.post(f"{AUTH}/login", json=invalid), 401)
    limited = client.post(f"{AUTH}/login", json=invalid)
    expect(limited, 429)
    assert limited.headers["Retry-After"] == "60"

    _, _, admin = moderator
    for _ in range(4):
        expect(client.post(f"{AUTH}/admin/unlock", headers=admin, json={"admin_password": token_urlsafe(24)}), 403)
    expect(client.post(f"{AUTH}/admin/unlock", headers=admin, json={"admin_password": token_urlsafe(24)}), 429)


def test_internal_api_requires_service_key_and_gateway_blocks_it(client, member):
    _, user, headers = member
    expect(client.get(f"{AUTH}/internal/v1/principal", headers=headers), 404)
    expect(client.get(f"{MODERATION}/internal/v1/comment-permission/{user['id']}"), 404)
    code = """import json,os,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
data=json.load(sys.stdin)
for url in data['urls']:
    try:
        urlopen(Request(url,headers=data['headers']),timeout=6)
    except HTTPError as error:
        assert error.code==401
    else:
        raise AssertionError('Missing service authentication')
    request=Request(url,headers={**data['headers'],'X-Internal-Key':os.environ['INTERNAL_AUTH_SECRET']})
    assert urlopen(request,timeout=6).status==200
"""
    compose("exec", "-T", "auth", "python", "-c", code, data={
        "headers": headers, "urls": ["http://auth:8000/internal/v1/principal",
                                   f"http://moderation:8000/internal/v1/comment-permission/{user['id']}"],
    })


def test_audit_visibility_and_change_records(client, member, moderator, super_admin):
    _, user, _ = member
    _, mod, admin = moderator
    rid = uuid4().hex
    blocked = expect(restriction(client, {**admin, "X-Request-ID": rid}, user["id"]), 201)
    expect(lift(client, super_admin, blocked["id"]), 200)
    own = expect(client.get(f"{MODERATION}/admin/audit", headers=admin), 200)
    all_events = expect(client.get(f"{MODERATION}/admin/audit", headers=super_admin), 200)
    assert all(event["actor_id"] == mod["id"] for event in own)
    assert any(event["request_id"] == rid and event["action"] == "comment_restricted" for event in own)
    assert any(event["target_id"] == blocked["id"] and event["action"] == "comment_restriction_lifted" for event in all_events)
    roles = expect(client.get(f"{AUTH}/admin/audit", headers=super_admin), 200)
    assert any(event["target_id"] == mod["id"] and event["new_role"] == "moderator" for event in roles)
    stats = expect(client.get(f"{MODERATION}/admin/stats", headers=admin), 200)
    assert stats["actions"]["comment_restricted"] == 1


def test_openapi_auth_contract(client):
    for service, admin_path in ((AUTH, "/admin/users"), (MODERATION, "/reports/{report_id}")):
        schema = expect(client.get(f"{service}/openapi.json"), 200)
        assert schema["paths"][admin_path]["get"]["security"] == [{"AccessToken": [], "AdminSession": []}]
        assert not any(path.startswith("/internal") for path in schema["paths"])


def test_sensitive_values_absent_from_logs_and_responses(client, super_admin):
    logs = compose("logs", "--no-color", "auth", "moderation", "gateway")
    for key in ("JWT_SECRET", "INTERNAL_AUTH_SECRET", "CYBERNEWS_TEST_SUPER_PASSWORD", "CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"):
        if os.environ[key] in logs:
            pytest.fail(f"Sensitive value present in logs ({key})")
    profile = expect(client.get(f"{AUTH}/me", headers=super_admin), 200)
    assert "password" not in json.dumps(profile) and "auth_version" not in profile
    if super_admin["X-Admin-Session"] in logs or super_admin["Authorization"].split(" ")[1] in logs:
        pytest.fail("A session credential appears in logs")

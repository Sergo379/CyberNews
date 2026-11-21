"""Stage 4 integration tests using isolated PostgreSQL, RabbitMQ and Gateway."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from secrets import token_urlsafe
from time import monotonic, sleep
from uuid import UUID, uuid4

import httpx
import pytest

AUTH = "/api/v1/auth"
NEWS = "/api/v1/articles"
COMMUNITY = "/api/v1/community"
MOD = "/api/v1/moderation"
NOTIFY = "/api/v1/notifications"
COLLECTOR = "/api/v1/collector"
BACKENDS = (AUTH, COLLECTOR, NEWS, COMMUNITY, MOD, NOTIFY)


def expect(response, code):
    assert response.status_code == code, (
        f"{response.request.method} {response.request.url.path} returned {response.status_code}, expected {code}"
    )
    return response.json() if response.content and code < 300 else None


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=os.environ["CYBERNEWS_TEST_BASE_URL"], trust_env=False,
                      timeout=14, follow_redirects=False) as session:
        yield session


def compose(*args, data=None):
    project = os.environ["CYBERNEWS_TEST_PROJECT"]
    assert project.startswith("cybernews-stage4-")
    execution = subprocess.run(
        [os.environ["CYBERNEWS_TEST_DOCKER"], "compose", "-f", "compose.yaml", "-f", "tests/stage2.compose.yaml",
         "-f", "tests/stage3.compose.yaml", "-f", "tests/stage4.compose.yaml", "-p", project, *args],
        input=json.dumps(data) if data is not None else None, capture_output=True, text=True, check=False,
    )
    assert execution.returncode == 0, f"Isolated Compose {args[0]} failed"
    return execution.stdout.strip()


def sql(owner, database, query):
    return compose("exec", "-T", "postgres", "psql", "-X", "-U", owner, "-d", database,
                   "-v", "ON_ERROR_STOP=1", "-Atc", query)


def wait_for(probe, timeout=40):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if value := probe():
            return value
        sleep(0.25)
    pytest.fail("Timed out waiting for asynchronous operation")


def login(client, email, password):
    payload = expect(client.post(f"{AUTH}/login", json={"email": email, "password": password}), 200)
    return {"Authorization": f"Bearer {payload['access_token']}"}


def add_session(client, headers, password):
    result = expect(client.post(f"{AUTH}/admin/unlock", headers=headers, json={"admin_password": password}), 200)
    return {**headers, "X-Admin-Session": result["admin_session"]}


@pytest.fixture(scope="session")
def admin(client):
    headers = login(client, os.environ["CYBERNEWS_TEST_SUPER_EMAIL"], os.environ["CYBERNEWS_TEST_SUPER_PASSWORD"])
    return add_session(client, headers, os.environ["CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"])


def member_account(client):
    suffix = uuid4().hex[:12]
    email = f"member-{suffix}@example.com"
    password = token_urlsafe(24)
    data = {"email": email, "nickname": f"member-{suffix}", "password": password}
    profile = expect(client.post(f"{AUTH}/register", json=data), 201)
    return profile, login(client, email, password), password


@pytest.fixture
def member(client):
    profile, credentials, _ = member_account(client)
    return profile, credentials


@pytest.fixture(scope="session")
def moderator(client, admin):
    profile, _, password = member_account(client)
    expect(client.patch(f"{AUTH}/admin/users/{profile['id']}/role", headers=admin,
                        json={"role": "moderator"}), 200)
    headers = login(client, profile["email"], password)
    secret = token_urlsafe(24)
    expect(client.put(f"{AUTH}/admin/password", headers=headers,
                      json={"current_password": password, "admin_password": secret}), 204)
    return profile, add_session(client, headers, secret)


def article_create(client, admin, category="other", status="published"):
    return expect(client.post(f"{NEWS}/admin/articles", headers=admin, json={
        "title": f"Stage 4 article {uuid4().hex[:10]}", "content": "<p>Original test article.</p>",
        "category": category, "status": status,
    }), 201)


@pytest.fixture
def article(client, admin):
    return article_create(client, admin)


def article_action(client, admin, article, action):
    return expect(client.post(f"{NEWS}/admin/articles/{article['id']}/{action}", headers=admin), 200)


def comment_url(article):
    return f"{COMMUNITY}/articles/{article['id']}/comments"


def post_comment(client, headers, article, body="A concise test comment"):
    return client.post(comment_url(article), headers=headers, json={"body": body})


def comment_detail(comment):
    return f"{COMMUNITY}/comments/{comment['id']}"


def subscriptions(client, headers):
    return expect(client.get(f"{NOTIFY}/subscriptions", headers=headers), 200)


def notify_items(client, headers):
    return expect(client.get(f"{NOTIFY}/", headers=headers), 200)["items"]


def for_article(client, headers, article_id):
    return next((item for item in notify_items(client, headers) if item["article_id"] == article_id), None)


def delivered(article_id):
    key = str(UUID(article_id))
    return sql("article_svc", "article_db",
               f"SELECT count(*) FROM article_outbox WHERE article_id='{key}' AND delivered_at IS NOT NULL") == "1"


def test_end_to_end_user_flow(client, member, moderator, admin):
    _, user = member
    _, mod = moderator
    expect(client.put(f"{NOTIFY}/subscriptions/research", headers=user), 200)
    new = article_create(client, admin, "research")
    notice = wait_for(lambda: for_article(client, user, new["id"]))
    assert notice["title"] == new["title"] and not notice["read"]
    expect(client.patch(f"{NOTIFY}/{notice['id']}/read", headers=user), 204)
    assert for_article(client, user, new["id"])["read"]
    comment = expect(post_comment(client, user, new), 201)
    expect(client.put(f"{comment_detail(comment)}/reaction", headers=user, json={"reaction": "like"}), 200)
    expect(client.put(f"{COMMUNITY}/articles/{new['id']}/bookmark", headers=user), 200)
    restriction = expect(client.post(f"{MOD}/restrictions", headers=mod, json={
        "user_id": member[0]["id"], "reason": "Fixture moderation",
    }), 201)
    expect(post_comment(client, user, new), 403)
    expect(client.patch(comment_detail(comment), headers=user, json={"body": "Blocked edit"}), 403)
    expect(client.post(f"{MOD}/restrictions/{restriction['id']}/lift", headers=admin,
                       json={"reason": "Fixture restore"}), 200)
    second = expect(post_comment(client, user, new, "Commenting is restored"), 201)
    assert second["id"] != comment["id"]
    stats = expect(client.get(f"{COMMUNITY}/articles/{new['id']}/stats", headers=user), 200)
    assert stats["comments"] == 2 and stats["bookmarked"] is True


def test_comment_crud_nickname_and_guest_reaction(client, article, member):
    profile, headers = member
    comment = expect(post_comment(client, headers, article, "  First comment body  "), 201)
    assert comment["nickname"] == profile["nickname"] and comment["author_id"] == profile["id"]
    assert comment["body"] == "First comment body" and not comment["edited"]
    author_name = expect(client.patch(f"{AUTH}/me", headers=headers, json={"nickname": "changed-" + uuid4().hex[:8]}), 200)
    assert author_name["nickname"] != comment["nickname"]
    edited = expect(client.patch(comment_detail(comment), headers=headers, json={"body": "Edited"}), 200)
    assert edited["edited"] and edited["edited_at"] and edited["nickname"] == comment["nickname"]
    read = expect(client.get(comment_detail(comment)), 200)
    assert read["my_reaction"] is None
    expect(client.delete(comment_detail(comment), headers=headers), 204)
    expect(client.delete(comment_detail(comment), headers=headers), 204)
    expect(client.get(comment_detail(comment)), 404)
    expect(client.patch(comment_detail(comment), headers=headers, json={"body": "Republish"}), 409)


@pytest.mark.parametrize(("method", "status"), [("PATCH", 403), ("DELETE", 403)])
def test_comment_owner_only(client, article, member, method, status):
    _, author = member
    _, intruder, _ = member_account(client)
    comment = expect(post_comment(client, author, article), 201)
    expect(client.request(method, comment_detail(comment), headers=intruder,
                          json={"body": "Attempt"} if method == "PATCH" else None), status)


def test_guest_cannot_create_comment_or_react(client, article):
    expect(client.post(comment_url(article), json={"body": "No account"}), 401)
    expect(client.put(f"{COMMUNITY}/articles/{article['id']}/reaction", json={"reaction": "like"}), 401)


@pytest.mark.parametrize("body", ["    ", "x" * 5001, "<script>not_text()</script>"])
def test_comment_validation(client, article, member, body):
    expect(post_comment(client, member[1], article, body), 422)


def test_comment_sanitizes_markup_and_rejects_author_fields(client, article, member):
    _, headers = member
    row = expect(post_comment(client, headers, article, "<b>Keep this</b><script>discardMe()</script>"), 201)
    assert row["body"] == "Keep this"
    expect(client.post(comment_url(article), headers={**headers, "X-User-ID": str(uuid4())},
                       json={"body": "Attempt", "author_id": str(uuid4())}), 422)


def test_comment_pagination_and_sort(client, article, member):
    _, headers = member
    rows = [expect(post_comment(client, headers, article, f"Page item {index}"), 201) for index in range(3)]
    oldest = expect(client.get(comment_url(article), params={"limit": 1, "offset": 1}), 200)
    newest = expect(client.get(comment_url(article), params={"limit": 1, "sort": "newest"}), 200)
    assert oldest["total"] == 3 and oldest["items"][0]["id"] == rows[1]["id"]
    assert newest["items"][0]["id"] == rows[-1]["id"]
    expect(client.get(comment_url(article), params={"limit": 101}), 422)


def test_hidden_draft_and_missing_articles(client, article, member, admin):
    _, headers = member
    comment = expect(post_comment(client, headers, article), 201)
    article_action(client, admin, article, "hide")
    expect(post_comment(client, headers, article), 404)
    expect(client.get(comment_url(article)), 404)
    expect(client.get(comment_detail(comment)), 404)
    expect(client.get(f"{COMMUNITY}/articles/{article['id']}/stats"), 404)
    expect(client.put(f"{COMMUNITY}/articles/{article['id']}/reaction", headers=headers,
                      json={"reaction": "like"}), 404)
    expect(post_comment(client, headers, {"id": str(uuid4())}), 404)
    draft = article_create(client, admin, status="draft")
    expect(post_comment(client, headers, draft), 404)
    article_action(client, admin, article, "restore")
    expect(client.get(comment_detail(comment)), 200)


def test_blocked_account_loses_write_access(client, article, member, admin):
    user, headers = member
    row = expect(post_comment(client, headers, article), 201)
    expect(client.post(f"{AUTH}/admin/users/{user['id']}/suspend", headers=admin, json={"reason": "Fixture suspension"}), 200)
    for verb, path, body in (
        ("POST", comment_url(article), {"body": "Blocked"}),
        ("PATCH", comment_detail(row), {"body": "Blocked"}),
        ("DELETE", comment_detail(row), None),
        ("PUT", f"{COMMUNITY}/articles/{article['id']}/reaction", {"reaction": "like"}),
        ("PUT", f"{comment_detail(row)}/reaction", {"reaction": "like"}),
        ("PUT", f"{COMMUNITY}/articles/{article['id']}/bookmark", None),
        ("PUT", f"{NOTIFY}/subscriptions/other", None),
    ):
        expect(client.request(verb, path, headers=headers, json=body), 401)


def test_moderation_outage_fails_closed_but_deletion_works(client, article, member):
    _, headers = member
    row = expect(post_comment(client, headers, article), 201)
    compose("stop", "moderation")
    try:
        expect(post_comment(client, headers, article), 503)
        expect(client.patch(comment_detail(row), headers=headers, json={"body": "Blocked"}), 503)
        expect(client.delete(comment_detail(row), headers=headers), 204)
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "60", "moderation")
    expect(post_comment(client, headers, article, "After Moderation recovered"), 201)


def test_article_outage_fails_closed(client, article, member):
    _, headers = member
    compose("stop", "articles")
    try:
        expect(post_comment(client, headers, article), 503)
        expect(client.get(comment_url(article)), 503)
        expect(client.post(f"{MOD}/reports", headers=headers, json={
            "target_type": "article", "target_id": article["id"], "reason": "Fixture dependency error",
        }), 503)
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "60", "articles")
    assert expect(client.get(comment_url(article)), 200)["total"] == 0


def test_account_comment_rate_limit(client, article, member):
    _, headers = member
    for index in range(12):
        expect(post_comment(client, headers, article, f"Rate fixture {index}"), 201)
    padded = post_comment(client, headers, article, "Rate limit should apply to the account")
    expect(padded, 429)
    assert padded.headers["Retry-After"] == "60"
    _, another, _ = member_account(client)
    expect(post_comment(client, another, article), 201)


def test_article_upsert_switch_removal_and_two_voters(client, article, member):
    _, headers = member
    _, another, _ = member_account(client)
    base = f"{COMMUNITY}/articles/{article['id']}"
    for reaction, expected in (("like", (1, 0)), ("like", (1, 0)), ("dislike", (0, 1))):
        result = expect(client.put(f"{base}/reaction", headers=headers, json={"reaction": reaction}), 200)
        assert (result["likes"], result["dislikes"]) == expected and result["my_reaction"] == reaction
    result = expect(client.put(f"{base}/reaction", headers=another, json={"reaction": "like"}), 200)
    assert result["likes"] == result["dislikes"] == 1
    public = expect(client.get(f"{base}/reactions"), 200)
    assert public["my_reaction"] is None
    result = expect(client.delete(f"{base}/reaction", headers=headers), 200)
    assert result == {"likes": 1, "dislikes": 0, "my_reaction": None}


def test_concurrent_reactions_have_one_active_row(client, article, member):
    _, headers = member
    target = f"{COMMUNITY}/articles/{article['id']}"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: client.put(f"{target}/reaction", headers=headers, json={"reaction": "like"}), range(8)))
    assert all(response.status_code == 200 for response in results)
    value = expect(client.get(f"{target}/reactions", headers=headers), 200)
    assert value == {"likes": 1, "dislikes": 0, "my_reaction": "like"}


def test_comment_reactions_independent_from_article_reaction(client, article, member):
    _, headers = member
    row = expect(post_comment(client, headers, article), 201)
    url = comment_detail(row)
    expect(client.put(f"{url}/reaction", headers=headers, json={"reaction": "like"}), 200)
    result = expect(client.put(f"{url}/reaction", headers=headers, json={"reaction": "dislike"}), 200)
    assert result == {"likes": 0, "dislikes": 1, "my_reaction": "dislike"}
    listed = expect(client.get(comment_url(article), headers=headers), 200)["items"][0]
    assert listed["dislikes"] == 1 and listed["my_reaction"] == "dislike"
    assert expect(client.get(f"{COMMUNITY}/articles/{article['id']}/reactions"), 200)["dislikes"] == 0
    assert expect(client.delete(f"{url}/reaction", headers=headers), 200)["dislikes"] == 0


def test_bookmarks_private_idempotent_and_hidden_redacted(client, article, member, admin):
    _, headers = member
    _, another, _ = member_account(client)
    url = f"{COMMUNITY}/articles/{article['id']}/bookmark"
    saved = expect(client.put(url, headers=headers), 200)
    assert expect(client.put(url, headers=headers), 200) == saved
    assert expect(client.get(url, headers=another), 200)["bookmarked"] is False
    assert expect(client.get(f"{COMMUNITY}/bookmarks", headers=another), 200) == []
    expect(client.get(f"{COMMUNITY}/bookmarks"), 401)
    article_action(client, admin, article, "hide")
    row = expect(client.get(f"{COMMUNITY}/bookmarks", headers=headers), 200)[0]
    assert not row["available"] and row["article"] is None
    expect(client.delete(url, headers=headers), 204)
    expect(client.delete(url, headers=headers), 204)
    assert expect(client.get(f"{COMMUNITY}/bookmarks", headers=headers), 200) == []


def test_batch_card_stats_omit_hidden_and_guest_reaction(client, article, member, admin):
    hidden = article_create(client, admin)
    article_action(client, admin, hidden, "hide")
    _, headers = member
    expect(post_comment(client, headers, article), 201)
    url = f"{COMMUNITY}/articles/{article['id']}"
    expect(client.put(f"{url}/reaction", headers=headers, json={"reaction": "like"}), 200)
    expect(client.put(f"{url}/bookmark", headers=headers), 200)
    payload = {"ids": [article["id"], hidden["id"], article["id"]]}
    items = expect(client.post(f"{COMMUNITY}/articles/stats", headers=headers, json=payload), 200)
    assert items == [{"article_id": article["id"], "likes": 1, "dislikes": 0, "my_reaction": "like",
                      "bookmarked": True, "comments": 1}]
    guest = expect(client.post(f"{COMMUNITY}/articles/stats", json=payload), 200)[0]
    assert guest["my_reaction"] is None and guest["bookmarked"] is None


def test_comment_hide_restore_audit_and_idempotency(client, article, member, moderator, admin):
    _, author = member
    _, mod = moderator
    row = expect(post_comment(client, author, article), 201)
    expect(client.put(f"{comment_detail(row)}/reaction", headers=author, json={"reaction": "like"}), 200)
    url = f"{MOD}/comments/{row['id']}"
    reviewed = expect(client.get(url, headers=mod), 200)
    assert reviewed["body"] == row["body"]
    key = str(uuid4())
    propagated = uuid4().hex
    action_headers = {**mod, "Idempotency-Key": key, "X-Request-ID": propagated}
    hidden = expect(client.post(f"{url}/hide", headers=action_headers, json={"reason": "Rule violated"}), 200)
    repeated = expect(client.post(f"{url}/hide", headers=action_headers, json={"reason": "Rule violated"}), 200)
    assert repeated == hidden and hidden["id"] == key and hidden["result"] == "applied"
    expect(client.get(comment_detail(row)), 404)
    expect(client.patch(comment_detail(row), headers=author, json={"body": "Trying again"}), 409)
    expect(client.put(f"{comment_detail(row)}/reaction", headers=author, json={"reaction": "like"}), 404)
    expect(client.post(f"{url}/restore", headers=mod, json={"reason": "Not allowed"}), 403)
    restored = expect(client.post(f"{url}/restore", headers=admin, json={"reason": "Decision changed"}), 200)
    assert restored["status"] == "published" and expect(client.get(comment_detail(row)), 200)["likes"] == 1
    history = expect(client.get(f"{url}/history", headers=admin), 200)
    assert {item["id"] for item in history} == {key, restored["id"]}
    events = expect(client.get(f"{MOD}/admin/audit", headers=mod), 200)
    assert [event["request_id"] for event in events if event["target_id"] == row["id"]] == [propagated]


def test_moderator_cannot_hide_admin_comment(client, article, moderator, admin):
    _, mod = moderator
    row = expect(post_comment(client, admin, article), 201)
    expect(client.post(f"{MOD}/comments/{row['id']}/hide", headers=mod, json={"reason": "No authority"}), 403)
    expect(client.get(comment_detail(row)), 200)


def test_moderation_durable_command_retries_after_dependency_outage(client, article, member, moderator, admin):
    row = expect(post_comment(client, member[1], article), 201)
    _, mod = moderator
    url = f"{MOD}/comments/{row['id']}"
    key = str(uuid4())
    headers = {**mod, "Idempotency-Key": key}
    compose("stop", "community")
    try:
        expect(client.post(f"{url}/hide", headers=headers, json={"reason": "Deferred command"}), 503)
        expect(client.post(f"{MOD}/reports", headers=member[1], json={
            "target_type": "comment", "target_id": row["id"], "reason": "Fixture dependency error",
        }), 503)
        events = expect(client.get(f"{MOD}/admin/audit", headers=mod), 200)
        assert not any(event["target_id"] == row["id"] for event in events)
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "60", "community")
    history = wait_for(lambda: expect(client.get(f"{url}/history", headers=admin), 200))
    assert history[0]["id"] == key and history[0]["status"] == "hidden"
    response = expect(client.post(f"{url}/hide", headers=headers, json={"reason": "Deferred command"}), 200)
    assert response["id"] == key and response["result"] == "applied"


def test_moderation_replays_result_already_committed_in_community(client, article, member, moderator, admin):
    row = expect(post_comment(client, member[1], article), 201)
    profile, headers = moderator
    command_id = str(uuid4())
    code = """import httpx,json,os,sys
value=json.load(sys.stdin)
response=httpx.post('http://community:8000/internal/v1/review/comments/'+value['comment_id']+'/commands',
                    json=value['command'],headers={'X-Internal-Key':os.environ['COMMUNITY_MODERATION_SECRET']})
assert response.status_code==200 and response.json()['result']=='applied'
print('OK')
"""
    assert compose("exec", "-T", "moderation", "python", "-c", code, data={
        "comment_id": row["id"], "command": {
            "command_id": command_id, "actor_id": profile["id"], "actor_role": "moderator",
            "reason": "Replay fixture", "action": "hide",
        },
    }) == "OK"
    url = f"{MOD}/comments/{row['id']}"
    replay_headers = {**headers, "Idempotency-Key": command_id}
    for _ in range(2):
        event = expect(client.post(f"{url}/hide", headers=replay_headers, json={"reason": "Replay fixture"}), 200)
        assert event["id"] == command_id
    history = expect(client.get(f"{url}/history", headers=admin), 200)
    assert len(history) == 1
    audit = expect(client.get(f"{MOD}/admin/audit", headers=headers), 200)
    assert len([event for event in audit if event["target_id"] == row["id"]]) == 1


@pytest.mark.parametrize("kind", ["article", "comment", "user"])
def test_report_target_has_to_exist(client, article, member, kind):
    user, headers = member
    payload = {"target_type": kind, "target_id": str(uuid4()), "reason": "Fixture report"}
    expect(client.post(f"{MOD}/reports", headers=headers, json=payload), 404)
    if kind == "user":
        payload["target_id"] = user["id"]
    elif kind == "article":
        payload["target_id"] = article["id"]
    else:
        payload["target_id"] = expect(post_comment(client, headers, article), 201)["id"]
    expect(client.post(f"{MOD}/reports", headers=headers, json=payload), 201)


def test_hidden_comment_not_reportable_and_internal_routes_protected(client, article, member, admin):
    row = expect(post_comment(client, member[1], article), 201)
    internal = f"/internal/v1/comments/{row['id']}/target"
    expect(client.get(f"{COMMUNITY}{internal}"), 404)
    expect(client.get(f"{NEWS}/internal/v1/articles/{article['id']}"), 404)
    expect(client.post(f"{MOD}/comments/{row['id']}/hide", headers=admin, json={"reason": "Fixture hide"}), 200)
    expect(client.post(f"{MOD}/reports", headers=member[1], json={
        "target_type": "comment", "target_id": row["id"], "reason": "Hidden comment",
    }), 404)
    code = """import httpx,os,sys,json
data=json.load(sys.stdin)
for url in data['urls']:
    assert httpx.get(url).status_code==401
    assert httpx.get(url,headers={'X-Internal-Key':os.environ['INTERNAL_AUTH_SECRET']}).status_code==401
print('OK')
"""
    output = compose("exec", "-T", "community", "python", "-c", code, data={
        "urls": [f"http://community:8000{internal}", f"http://articles:8000/internal/v1/articles/{article['id']}"],
    })
    assert output == "OK"


def test_subscription_idempotence_invalid_category_and_unsubscribe(client, member):
    _, headers = member
    url = f"{NOTIFY}/subscriptions/malware"
    first = expect(client.put(url, headers=headers), 200)
    assert expect(client.put(url, headers=headers), 200) == first
    assert subscriptions(client, headers) == [first]
    expect(client.put(f"{NOTIFY}/subscriptions/unknown", headers=headers), 422)
    expect(client.delete(url, headers=headers), 204)
    expect(client.delete(url, headers=headers), 204)
    assert subscriptions(client, headers) == []


def test_notifications_are_private_and_unread_count_is_idempotent(client, member, admin):
    _, headers = member
    _, other, _ = member_account(client)
    _, unsubscribed, _ = member_account(client)
    expect(client.put(f"{NOTIFY}/subscriptions/software-security", headers=headers), 200)
    expect(client.put(f"{NOTIFY}/subscriptions/malware", headers=other), 200)
    story = article_create(client, admin, "software-security")
    found = wait_for(lambda: for_article(client, headers, story["id"]))
    assert expect(client.get(f"{NOTIFY}/unread-count", headers=headers), 200)["count"] == 1
    assert for_article(client, other, story["id"]) is None
    assert for_article(client, unsubscribed, story["id"]) is None
    expect(client.get(f"{NOTIFY}/"), 401)
    expect(client.patch(f"{NOTIFY}/{found['id']}/read", headers=other), 404)
    expect(client.patch(f"{NOTIFY}/{found['id']}/read", headers=headers), 204)
    read_at = for_article(client, headers, story["id"])["read_at"]
    expect(client.patch(f"{NOTIFY}/{found['id']}/read", headers=headers), 204)
    assert for_article(client, headers, story["id"])["read_at"] == read_at
    assert expect(client.get(f"{NOTIFY}/unread-count", headers=headers), 200)["count"] == 0


def test_hidden_article_notification_redacted_and_unsubscribe_preserves_notice(client, member, admin):
    _, headers = member
    expect(client.put(f"{NOTIFY}/subscriptions/data-breaches", headers=headers), 200)
    story = article_create(client, admin, "data-breaches")
    found = wait_for(lambda: for_article(client, headers, story["id"]))
    expect(client.delete(f"{NOTIFY}/subscriptions/data-breaches", headers=headers), 204)
    assert for_article(client, headers, story["id"])["id"] == found["id"]
    article_action(client, admin, story, "hide")
    hidden = next(item for item in notify_items(client, headers) if item["id"] == found["id"])
    assert not hidden["available"] and all(hidden[field] is None for field in ("article_id", "title", "category"))
    assert expect(client.post(f"{NOTIFY}/read-all", headers=headers), 200)["updated"] == 1
    assert expect(client.post(f"{NOTIFY}/read-all", headers=headers), 200)["updated"] == 0


def test_draft_and_edits_raise_exactly_one_first_publication_event(client, member, admin):
    _, headers = member
    expect(client.put(f"{NOTIFY}/subscriptions/vulnerabilities", headers=headers), 200)
    story = article_create(client, admin, "vulnerabilities", "draft")
    identifier = str(UUID(story["id"]))
    query = f"SELECT count(*) FROM article_outbox WHERE article_id='{identifier}'"
    assert sql("article_svc", "article_db", query) == "0"
    url = f"{NEWS}/admin/articles/{identifier}"
    expect(client.patch(url, headers=admin, json={"status": "published"}), 200)
    wait_for(lambda: for_article(client, headers, identifier))
    event_before = sql("article_svc", "article_db", f"SELECT event_id FROM article_outbox WHERE article_id='{identifier}'")
    expect(client.patch(url, headers=admin, json={"title": "Edited published fixture"}), 200)
    article_action(client, admin, story, "hide")
    article_action(client, admin, story, "restore")
    expect(client.patch(url, headers=admin, json={"status": "draft"}), 200)
    expect(client.patch(url, headers=admin, json={"status": "published"}), 200)
    assert sql("article_svc", "article_db", query) == "1"
    assert sql("article_svc", "article_db", f"SELECT event_id FROM article_outbox WHERE article_id='{identifier}'") == event_before


def test_rss_first_publication_but_repeat_has_no_outbox_event(client, admin):
    wait_for(lambda: expect(client.get(f"{COLLECTOR}/status", headers=admin), 200)["last_run"])
    def complete():
        result = expect(client.get(f"{COLLECTOR}/status", headers=admin), 200)["last_run"]
        return result if result["status"] not in {"running", "queued"} else None
    wait_for(complete)
    sql_query = ("SELECT count(*) FROM article_outbox o JOIN articles a ON a.id=o.article_id "
                 "WHERE a.source_id IS NOT NULL AND o.delivered_at IS NOT NULL")
    wait_for(lambda: sql("article_svc", "article_db", sql_query) == "3")
    run = expect(client.post(f"{COLLECTOR}/sync", headers=admin), 202)
    wait_for(complete)
    latest = expect(client.get(f"{COLLECTOR}/runs/{run['id']}", headers=admin), 200)
    assert sum(row["created"] for row in latest["sources"]) == 0
    assert sql("article_svc", "article_db", sql_query) == "3"


def publish_message(event, correct=True):
    program = """import json,sys,pika
from app.config import broker
from cybernews_runtime.broker import EXCHANGE, ROUTING_KEY, declare_topology
data=json.load(sys.stdin)
with broker.connect() as connection:
    channel=connection.channel()
    declare_topology(channel)
    channel.confirm_delivery()
    event=data['event']
    channel.basic_publish(EXCHANGE,ROUTING_KEY,json.dumps(event).encode(),
        properties=pika.BasicProperties(message_id=event['event_id'],content_type='application/json',
                                        type=ROUTING_KEY,delivery_mode=2),mandatory=True)
print('OK')
"""
    if not correct:
        event = {**event, "event_version": 99}
    assert compose("exec", "-T", "articles", "python", "-c", program, data={"event": event}) == "OK"


def test_duplicate_rabbit_event_and_invalid_version_are_handled(client, member, admin):
    _, headers = member
    expect(client.put(f"{NOTIFY}/subscriptions/malware", headers=headers), 200)
    story = article_create(client, admin, "malware")
    notice = wait_for(lambda: for_article(client, headers, story["id"]))
    identifier = str(UUID(story["id"]))
    event = json.loads(sql("article_svc", "article_db", f"""SELECT json_build_object(
        'event_id',event_id,'event_type','article.published','event_version',1,'article_id',article_id,
        'category',category,'source_id',source_id,'published_at',published_at,'created_at',created_at)
        FROM article_outbox WHERE article_id='{identifier}'"""))
    publish_message(event)
    publish_message({**event, "event_id": str(uuid4())}, correct=False)
    def quarantine():
        rows = compose("exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "list_queues", "-p", "cybernews-stage4",
                       "name", "messages_ready", "messages_unacknowledged")
        return "cybernews.notifications.dead.v1\t1\t0" in rows and "article-published.v1\t0\t0" in rows
    wait_for(quarantine)
    same_article = [item["id"] for item in notify_items(client, headers) if item["article_id"] == identifier]
    assert same_article == [notice["id"]]


def test_outbox_survives_broker_downtime_and_late_subscriptions(client, member, admin):
    _, subscribed = member
    _, late, _ = member_account(client)
    _, removed, _ = member_account(client)
    for headers in (subscribed, removed):
        expect(client.put(f"{NOTIFY}/subscriptions/cyberattacks", headers=headers), 200)
    compose("stop", "rabbitmq")
    try:
        story = article_create(client, admin, "cyberattacks")
        identifier = str(UUID(story["id"]))
        assert not delivered(identifier)
        assert sql("article_svc", "article_db",
                   f"SELECT count(*) FROM article_outbox WHERE article_id='{identifier}'") == "1"
        expect(client.put(f"{NOTIFY}/subscriptions/cyberattacks", headers=late), 200)
        expect(client.delete(f"{NOTIFY}/subscriptions/cyberattacks", headers=removed), 204)
        compose("restart", "articles")
        assert not delivered(identifier)
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "100", "rabbitmq", "articles", "notifications")
    notice = wait_for(lambda: for_article(client, subscribed, story["id"]))
    assert notice["available"] and delivered(story["id"])
    assert for_article(client, late, story["id"]) is None
    assert for_article(client, removed, story["id"]) is None


def test_confirmed_persistent_message_survives_broker_restart_without_consumer(client, member, admin):
    _, headers = member
    expect(client.put(f"{NOTIFY}/subscriptions/software-security", headers=headers), 200)
    compose("stop", "notifications")
    try:
        story = article_create(client, admin, "software-security")
        wait_for(lambda: delivered(story["id"]))
        compose("restart", "rabbitmq")
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "100", "rabbitmq", "notifications")
    assert wait_for(lambda: for_article(client, headers, story["id"]))["available"]


def test_comment_bookmark_and_notification_persist_after_restart(client, member, admin):
    _, user = member
    expect(client.put(f"{NOTIFY}/subscriptions/research", headers=user), 200)
    story = article_create(client, admin, "research")
    note = wait_for(lambda: for_article(client, user, story["id"]))
    comment = expect(post_comment(client, user, story, "Persistent discussion"), 201)
    expect(client.put(f"{COMMUNITY}/articles/{story['id']}/bookmark", headers=user), 200)
    expect(client.patch(f"{NOTIFY}/{note['id']}/read", headers=user), 204)
    compose("stop", "collector", "community", "moderation", "notifications", "articles", "auth", "postgres")
    compose("up", "-d", "--wait", "--wait-timeout", "100", "postgres", "auth", "articles", "collector",
            "moderation", "community", "notifications", "gateway")
    assert expect(client.get(comment_detail(comment)), 200)["body"] == comment["body"]
    assert expect(client.get(f"{COMMUNITY}/bookmarks", headers=user), 200)[0]["article_id"] == story["id"]
    restored = for_article(client, user, story["id"])
    assert restored["id"] == note["id"] and restored["read"]


def test_postgres_outage_preserves_liveness_and_catalog(client, article):
    story = expect(client.get(f"{NEWS}/{article['id']}"), 200)
    compose("stop", "postgres")
    try:
        for prefix in BACKENDS:
            expect(client.get(f"{prefix}/health"), 200)
            expect(client.get(f"{prefix}/ready"), 503)
    finally:
        compose("up", "-d", "--wait", "--wait-timeout", "100", "postgres")
    wait_for(lambda: all(client.get(f"{prefix}/ready").status_code == 200 for prefix in BACKENDS))
    assert expect(client.get(f"{NEWS}/{article['id']}"), 200) == story


def test_database_isolation_and_idempotent_migrations(client, article):
    compose("cp", "tests/postgres-smoke.sh", "postgres:/tmp/lab2-postgres-smoke.sh")
    result = compose("exec", "-T", "postgres", "bash", "-c",
                     r"tr -d '\015' </tmp/lab2-postgres-smoke.sh | bash -s -- isolation smoke_00000000000000000000000000000000")
    assert result.count("(UTF-8, isolated)") == len(BACKENDS)
    story = expect(client.get(f"{NEWS}/{article['id']}"), 200)
    for prefix in BACKENDS:
        service = prefix.rsplit("/", 1)[-1]
        compose("exec", "-T", service, "alembic", "upgrade", "head")
        assert "(head)" in compose("exec", "-T", service, "alembic", "current", "--check-heads")
        assert "No new upgrade operations detected" in compose("exec", "-T", service, "alembic", "check")
    assert expect(client.get(f"{NEWS}/{article['id']}"), 200) == story

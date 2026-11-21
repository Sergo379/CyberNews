"""Exercise the real API Gateway and PostgreSQL with deterministic RSS transport."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from secrets import token_urlsafe
from time import monotonic, sleep
from uuid import uuid4

import httpx
import pytest

AUTH = "/api/v1/auth"
ARTICLES = "/api/v1/articles"
RSS = "/api/v1/collector"
ACTIVE_RUNS = {"queued", "running"}


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
    name = os.environ["CYBERNEWS_TEST_PROJECT"]
    assert name.startswith("cybernews-stage3-")
    result = subprocess.run(
        [os.environ["CYBERNEWS_TEST_DOCKER"], "compose", "-f", "compose.yaml", "-f", "tests/stage2.compose.yaml",
         "-f", "tests/stage3.compose.yaml", "-p", name, *args],
        input=json.dumps(data) if data is not None else None, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"Isolated Compose {args[0]} failed"
    return result.stdout


def login(client, email, password):
    value = expect(client.post(f"{AUTH}/login", json={"email": email, "password": password}), 200)
    return {"Authorization": f"Bearer {value['access_token']}"}


def unlock(client, access, password):
    value = expect(client.post(f"{AUTH}/admin/unlock", headers=access, json={"admin_password": password}), 200)
    return {**access, "X-Admin-Session": value["admin_session"]}


@pytest.fixture(scope="session")
def admin(client):
    access = login(client, os.environ["CYBERNEWS_TEST_SUPER_EMAIL"], os.environ["CYBERNEWS_TEST_SUPER_PASSWORD"])
    return unlock(client, access, os.environ["CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"])


@pytest.fixture
def member(client):
    nickname = "stage3-" + uuid4().hex[:10]
    data = {"nickname": nickname, "email": f"{nickname}@example.com", "password": token_urlsafe(24)}
    account = expect(client.post(f"{AUTH}/register", json=data), 201)
    return account, data


def await_value(callback, timeout=35):
    end = monotonic() + timeout
    while monotonic() < end:
        result = callback()
        if result:
            return result
        sleep(0.25)
    pytest.fail("Timed out waiting for API state")


def wait_run(client, admin, run_id):
    def finished():
        run = expect(client.get(f"{RSS}/runs/{run_id}", headers=admin), 200)
        return run if run["status"] not in ACTIVE_RUNS else None
    return await_value(finished)


@pytest.fixture(scope="session")
def startup(client, admin):
    def started():
        state = expect(client.get(f"{RSS}/status", headers=admin), 200)
        return state["last_run"]
    run = await_value(started)
    return wait_run(client, admin, run["id"])


def feed_sources(client, admin):
    return expect(client.get(f"{RSS}/sources", headers=admin), 200)


def source_id(client, admin, name):
    return next(src["id"] for src in feed_sources(client, admin) if src["name"] == name)


def detail(client, title_fragment):
    page = expect(client.get(f"{ARTICLES}/", params={"q": title_fragment}), 200)
    assert page["total"] == 1
    return expect(client.get(f"{ARTICLES}/{page['items'][0]['id']}"), 200)


def sync(client, admin, source):
    response = client.post(f"{RSS}/sources/{source}/sync", headers=admin)
    accepted = expect(response, 202)
    return wait_run(client, admin, accepted["id"])


def add_source(client, admin, name, path, **fields):
    return expect(client.post(f"{RSS}/sources", headers=admin, json={
        "name": name, "feed_url": f"https://rss-fixture.example{path}",
        "website_url": "https://rss-fixture.example/", **fields,
    }), 201)


def create_content(client, admin, **changes):
    return expect(client.post(f"{ARTICLES}/admin/articles", headers=admin, json={
        "title": "Editorial forest update",
        "summary": "Editorial summary",
        "content": "<h2>Editorial heading</h2><p>Original body.</p><script>unwantedScript()</script>",
        **changes,
    }), 201)


def test_startup_keeps_other_feeds_running_after_xml_error(client, admin, startup):
    result = {item["source_id"]: item for item in startup["sources"]}
    hacker = result[source_id(client, admin, "The Hacker News")]
    bleeping = result[source_id(client, admin, "BleepingComputer")]
    kreb = result[source_id(client, admin, "Krebs on Security")]
    assert startup["trigger"] == "startup" and startup["status"] == "partial"
    assert hacker["created"] == 2 and bleeping["created"] == 1
    assert kreb["status"] == "error" and kreb["error"] == "invalid_feed_xml"
    page = expect(client.get(f"{ARTICLES}/"), 200)
    assert page["total"] == 3
    single = detail(client, "Acorn")
    assert single["content_mode"] == "external_source" and single["content"] is None
    assert single["original_url"].endswith("?variant=stable&utm_source=feed") and single["image_url"] is None
    assert detail(client, "Birch")["published_at"] is None


def test_pagination_search_filters_sort_and_missing(client, admin, startup):
    newest = expect(client.get(f"{ARTICLES}/", params={"limit": 1, "sort": "newest"}), 200)
    oldest = expect(client.get(f"{ARTICLES}/", params={"limit": 1, "sort": "oldest"}), 200)
    page2 = expect(client.get(f"{ARTICLES}/", params={"limit": 1, "offset": 1}), 200)
    assert newest["total"] == oldest["total"] == page2["total"] == 3
    assert (datetime.fromisoformat(newest["items"][0]["published_at"]) >
            datetime.fromisoformat(oldest["items"][0]["published_at"]))
    assert page2["items"][0]["id"] != newest["items"][0]["id"]
    source = source_id(client, admin, "The Hacker News")
    page = expect(client.get(f"{ARTICLES}/search", params={
        "q": "advisory", "category": "vulnerabilities", "source_id": source,
        "published_from": "2026-11-09T08:00:00Z", "published_to": "2026-11-09T09:00:00Z",
    }), 200)
    assert page["total"] == 1 and page["items"][0]["title"].startswith("Acorn")
    expect(client.get(f"{ARTICLES}/not-a-uuid"), 422)
    expect(client.get(f"{ARTICLES}/{uuid4()}"), 404)
    assert len(expect(client.get(f"{ARTICLES}/categories"), 200)) == 7
    assert sum(item["count"] for item in expect(client.get(f"{ARTICLES}/sources"), 200)) == 3


def test_conditional_sync_keeps_ids_and_count(client, admin, startup):
    previous = detail(client, "Acorn")
    hacker = source_id(client, admin, "The Hacker News")
    run = sync(client, admin, hacker)
    assert run["sources"][0]["status"] == "not_modified"
    current = detail(client, "Acorn")
    assert current["id"] == previous["id"] and current["published_at"] == previous["published_at"]
    assert expect(client.get(f"{ARTICLES}/"), 200)["total"] == 3


def test_same_feed_update_preserves_id_and_publication_date(client, admin, startup):
    previous = detail(client, "Acorn")
    hacker = source_id(client, admin, "The Hacker News")
    expect(client.patch(f"{RSS}/sources/{hacker}", headers=admin, json={
        "feed_url": "https://rss-fixture.example/changed",
    }), 200)
    run = sync(client, admin, hacker)
    assert run["sources"][0]["updated"] == 1 and run["sources"][0]["created"] == 0
    now = detail(client, "Acorn")
    assert now["title"] == "Acorn vulnerability updated"
    assert now["id"] == previous["id"] and now["published_at"] == previous["published_at"]


def test_parallel_manual_runs_have_one_winner(client, admin, startup):
    source = add_source(client, admin, "Busy test fixture", "/busy")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"{RSS}/sources/{source['id']}/sync", headers=admin), range(2)))
    assert sorted(reply.status_code for reply in results) == [202, 409]
    accepted = next(reply.json() for reply in results if reply.status_code == 202)
    result = wait_run(client, admin, accepted["id"])
    assert result["sources"][0]["created"] == 0
    assert result["sources"][0]["unchanged"] == 2


def test_source_admin_controls_and_error_history(client, admin, startup):
    expect(client.post(f"{RSS}/sources", headers=admin, json={
        "name": "Invalid URL", "feed_url": "http://localhost/data", "website_url": "https://rss-fixture.example/",
    }), 422)
    source = add_source(client, admin, "Down test fixture", "/down")
    error = sync(client, admin, source["id"])["sources"][0]
    assert error["error"] == "feed_http_502"
    expect(client.patch(f"{RSS}/sources/{source['id']}", headers=admin, json={"active": False}), 200)
    expect(client.post(f"{RSS}/sources/{source['id']}/sync", headers=admin), 409)
    expect(client.get(f"{RSS}/runs", headers=admin, params={"limit": 1, "offset": 1}), 200)


def test_licensed_feed_and_immediate_revocation(client, admin, startup):
    source = add_source(client, admin, "Licensed fixture", "/licensed",
                        content_policy="full_article", rights_reference="Fixture permission record", allow_images=True)
    sync(client, admin, source["id"])
    page = expect(client.get(f"{ARTICLES}/", params={"source_id": source["id"]}), 200)
    assert page["total"] == 1
    published = expect(client.get(f"{ARTICLES}/{page['items'][0]['id']}"), 200)
    assert published["content_mode"] == "full_article"
    assert "<h2>Test Full Heading</h2>" in published["content"] and published["image_url"]
    expect(client.patch(f"{RSS}/sources/{source['id']}", headers=admin, json={
        "content_policy": "external_source", "allow_images": False, "rights_reference": None,
    }), 200)
    revoked = expect(client.get(f"{ARTICLES}/{published['id']}"), 200)
    assert revoked["content_mode"] == "external_source" and revoked["content"] is None and revoked["image_url"] is None


def test_editorial_full_text_status_and_audit(client, admin):
    article = create_content(client, admin)
    url = f"{ARTICLES}/{article['id']}"
    admin_url = f"{ARTICLES}/admin/articles/{article['id']}"
    expect(client.get(url), 404)
    expect(client.patch(admin_url, headers=admin, json={"status": "published", "category": "research"}), 200)
    published = expect(client.get(url), 200)
    assert published["content_mode"] == "full_article" and published["published_at"]
    assert "<h2>Editorial heading</h2>" in published["content"] and "unwantedScript" not in published["content"]
    expect(client.post(f"{admin_url}/hide", headers=admin), 200)
    expect(client.get(url), 404)
    expect(client.post(f"{admin_url}/restore", headers=admin), 200)
    expect(client.get(url), 200)
    events = expect(client.get(f"{ARTICLES}/admin/audit", headers=admin), 200)
    assert {"article_created", "article_edited", "article_hidden", "article_restored"} <= {
        event["action"] for event in events if event["target_id"] == article["id"]
    }


@pytest.mark.parametrize("role", ["user", "moderator"])
def test_non_super_admin_cannot_modify_or_sync(client, admin, member, role):
    account, data = member
    if role == "moderator":
        expect(client.patch(f"{AUTH}/admin/users/{account['id']}/role", headers=admin, json={"role": role}), 200)
    headers = login(client, data["email"], data["password"])
    if role == "moderator":
        password = token_urlsafe(24)
        expect(client.put(f"{AUTH}/admin/password", headers=headers, json={
            "current_password": data["password"], "admin_password": password,
        }), 204)
        headers = unlock(client, headers, password)
    expect(client.post(f"{ARTICLES}/admin/articles", headers=headers, json={
        "title": "Denied story", "content": "<p>Checked</p>",
    }), 403)
    expect(client.post(f"{RSS}/sync", headers=headers), 403)


def test_internal_import_rejects_missing_or_auth_service_key_and_checks_identity(client):
    expect(client.post(f"{ARTICLES}/internal/v1/import", json={}), 404)
    result = compose("exec", "-T", "collector", "python", "-c", """import os
from uuid import uuid4
import httpx
base='http://articles:8000/internal/v1/import'
with httpx.Client(timeout=6) as client:
    for keys in ({}, {'X-Internal-Key': os.environ['INTERNAL_AUTH_SECRET']}):
        assert client.post(base,json={},headers=keys).status_code==401
    correct={'X-Internal-Key':os.environ['ARTICLE_IMPORT_SECRET']}
    assert client.post(base,json={},headers=correct).status_code==422
    policy={'revision':1,'content_policy':'external_source','allow_images':False}
    source=str(uuid4())
    first={'title':'Sequoia test identity','original_url':'https://rss-fixture.example/sequoia?edition=1','language':'en',
           'external_guid':'first','published_at':'2026-11-09T08:00:00Z'}
    second={**first,'title':'Other identity','original_url':'https://rss-fixture.example/sequoia?edition=2','external_guid':'second'}
    batch={'source_id':source,'source_name':'Identity fixture','source_url':'https://rss-fixture.example/','policy':policy}
    assert client.post(base,json={**batch,'entries':[first,second]},headers=correct).json()['created']==2
    diff={**first,'original_url':second['original_url']}
    assert client.post(base,json={**batch,'entries':[diff]},headers=correct).json()['conflicted']==1
    replay={**first,'original_url':first['original_url']+'&utm_medium=test'}
    assert client.post(base,json={**batch,'entries':[replay]},headers=correct).json()['unchanged']==1
    from concurrent.futures import ThreadPoolExecutor
    raced={**first,'original_url':'https://rss-fixture.example/cedar','external_guid':'parallel'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client.post(base,json={**batch,'entries':[raced]},headers=correct),range(2)))
    assert sorted((result.json()['created'], result.json()['unchanged']) for result in responses)==[(0,1),(1,0)]
print('OK')
""")
    assert result.strip() == "OK"


def test_health_readiness_and_json_logs(client, admin, startup):
    for api, service in ((RSS, "collector"), (ARTICLES, "articles")):
        expect(client.get(f"{api}/health"), 200)
        assert expect(client.get(f"{api}/ready"), 200)["database"] == "ok"
        logs = compose("logs", "--no-color", "--no-log-prefix", service)
        if any(os.environ[value] in logs for value in ("JWT_SECRET", "INTERNAL_AUTH_SECRET", "ARTICLE_IMPORT_SECRET")):
            pytest.fail("A secret appears in service logs")
        rows = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
        assert any(row["service"] == service and row["request_id"] and row["message"] for row in rows)


def test_scheduler_enqueues_every_30_minutes_without_overlap():
    result = compose("exec", "-T", "collector", "python", "-c", """from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from app import scheduler
clock=iter([0, 0, 1799, 1800, 3600])
events=[]
database=SimpleNamespace(engine=None, sessions=SimpleNamespace(begin=lambda: nullcontext(None)))
worker=scheduler.Scheduler(database,None,None,1800,True)
worker.recover=lambda: None
def run_queued():
    if len(events)==3:
        worker.stopping.set()
worker.run_queued=run_queued
with patch.object(scheduler,'monotonic',lambda: next(clock)), \
     patch.object(scheduler,'coordinator',lambda _: nullcontext(True)), \
     patch.object(scheduler,'queue_run',lambda _,kind: events.append(kind)), \
     patch.object(worker.wake,'wait'):
    worker.loop()
assert events==['startup','scheduled','scheduled']
print('OK')
""")
    assert result.strip() == "OK"


def test_import_unavailable_and_persistence_after_restart(client, admin, startup):
    article = create_content(client, admin, title="Persisted stage3 editorial", status="published")
    source = add_source(client, admin, "Import failure fixture", "/import-failure")
    compose("stop", "articles")
    try:
        failed = sync(client, admin, source["id"])["sources"][0]
        assert failed["error"] == "article_service_unavailable"
    finally:
        compose("start", "articles")
    compose("stop", "collector", "articles", "auth", "postgres")
    compose("up", "-d", "--wait", "--wait-timeout", "100", "postgres", "auth", "articles", "collector", "gateway")
    assert expect(client.get(f"{ARTICLES}/{article['id']}"), 200)["content"] == article["content"]
    assert expect(client.get(f"{RSS}/runs/{startup['id']}", headers=admin), 200)["trigger"] == "startup"
    assert expect(client.get(f"{RSS}/ready"), 200)["database"] == "ok"

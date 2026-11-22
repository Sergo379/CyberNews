"""Integration and recovery checks for the dedicated Docker Desktop lab3 namespace."""

import json
import os
import re
import secrets
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import pytest
from playwright.sync_api import expect as browser_expect

from test_stage5 import open_page, browser, capture, heading, route, signin, story_link, unlock

NAMESPACE = "cybernews-lab3"
SERVICES = ("auth", "collector", "articles", "community", "moderation", "notifications")
ROOT = Path(__file__).resolve().parents[1]


class Cluster:
    def __init__(self, executable):
        self.exe = executable

    def kubectl(self, *args, stdin=None):
        completed = subprocess.run([self.exe, *args], input=stdin, capture_output=True, timeout=210)
        assert completed.returncode == 0, "kubectl operation failed (" + args[0] + ")"
        return completed.stdout.decode("utf-8").strip()

    def run(self, *args, stdin=None):
        return self.kubectl("--context", "docker-desktop", "--namespace", NAMESPACE, *args, stdin=stdin)

    def get(self, kind, name):
        return json.loads(self.run("get", kind, name, "-o", "json"))

    def rollout(self, name):
        self.run("rollout", "status", name, "--timeout=175s")

    def scale(self, name, count):
        self.run("scale", name, "--replicas=" + str(count))

    def endpoints(self, name):
        slices = json.loads(self.run("get", "endpointslices", "-l", "kubernetes.io/service-name=" + name, "-o", "json"))
        return {item["targetRef"]["name"] for group in slices["items"] for item in group["endpoints"]
                if item["conditions"].get("ready") and item.get("targetRef", {}).get("kind") == "Pod"}

    def sql(self, database, owner, statement):
        return self.run("exec", "postgres-0", "--", "psql", "-X", "-U", owner, "-d", database,
                        "-v", "ON_ERROR_STOP=1", "-Atc", statement)

    def component_snapshot(self, name):
        pod = self.get("pod", name + "-0")
        claim = self.get("pvc", name + "-data")
        assert claim["status"]["phase"] == "Bound"
        return pod["metadata"]["uid"], claim["metadata"]["uid"], claim["spec"]["volumeName"]


def api(client, method, path, status, *, token=None, data=None):
    response = client.request(method, "/api/v1/" + path, headers=token or {}, json=data)
    assert response.status_code == status, f"{method} {path} returned {response.status_code}, expected {status}"
    return response.json() if response.content and status < 300 else None


def wait_until(predicate, *, seconds=90, description="expected state"):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        result = predicate()
        if result:
            return result
        sleep(0.7)
    pytest.fail(f"Timed out waiting for {description}")


@pytest.fixture(scope="session")
def cluster():
    if os.getenv("CYBERNEWS_LAB3_RUN") != "1":
        pytest.skip("Explicitly enable the isolated Lab 3 integration checks")
    kube = Cluster(os.getenv("CYBERNEWS_LAB3_KUBECTL", "kubectl"))
    assert kube.kubectl("config", "current-context") == "docker-desktop"
    view = json.loads(kube.run("config", "view", "--minify", "-o", "json"))
    target = view["clusters"][0]["cluster"]
    address = urlsplit(target["server"])
    assert address.scheme == "https" and address.hostname in ("127.0.0.1", "localhost", "kubernetes.docker.internal")
    assert not target.get("insecure-skip-tls-verify")
    assert any(item["metadata"]["name"] in ("desktop-control-plane", "docker-desktop")
               for item in json.loads(kube.run("get", "nodes", "-o", "json"))["items"])
    label = kube.get("namespace", NAMESPACE)["metadata"]["labels"]
    assert label["app.kubernetes.io/part-of"] == "cybernews" and label["app.kubernetes.io/version"] == "lab3"
    yield kube


@pytest.fixture(scope="session")
def origin(cluster):
    value = os.getenv("CYBERNEWS_LAB3_URL", "http://127.0.0.1:18080").rstrip("/")
    url = urlsplit(value)
    assert url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost") and url.port not in (None, 8080)
    assert not (url.username or url.password or url.path or url.query or url.fragment)
    response = httpx.get(value + "/health", timeout=12, trust_env=False)
    assert response.status_code == 200 and response.json()["environment"] == "kubernetes"
    return value


@pytest.fixture(scope="session")
def client(origin):
    with httpx.Client(base_url=origin, trust_env=False, timeout=15) as session:
        yield session


def log_in(client, email, password):
    credentials = api(client, "POST", "auth/login", 200, data={"email": email, "password": password})
    return {"Authorization": "Bearer " + credentials["access_token"]}


def elevate(client, token, password):
    session = api(client, "POST", "auth/admin/unlock", 200, token=token, data={"admin_password": password})
    return {**token, "X-Admin-Session": session["admin_session"]}


@pytest.fixture(scope="session")
def admin_credentials(cluster, client):
    keys = ("CYBERNEWS_LAB3_SUPER_EMAIL", "CYBERNEWS_LAB3_SUPER_PASSWORD", "CYBERNEWS_LAB3_ADMIN_PASSWORD")
    values = tuple(os.environ.get(key) for key in keys)
    if not all(values):
        pytest.fail("Provide the already bootstrapped Lab 3 administrator credentials through process environment")
    email, password, elevation = values
    return email, password, elevation


@pytest.fixture
def admin(client, admin_credentials):
    email, password, elevation = admin_credentials
    return elevate(client, log_in(client, email, password), elevation)


def create_user(client):
    account = "lab3-" + secrets.token_hex(5)
    email, password = f"{account}@example.com", secrets.token_urlsafe(24)
    profile = api(client, "POST", "auth/register", 201, data={"email": email, "nickname": account, "password": password})
    return profile, password, log_in(client, email, password)


def publish(client, admin, category="research"):
    title = "CyberNews Lab 3 · " + secrets.token_hex(5)
    return api(client, "POST", "articles/admin/articles", 201, token=admin, data={
        "title": title, "content": "<p>Kubernetes integration record</p>", "status": "published", "category": category,
    })


def notifications(client, token, article_id):
    result = api(client, "GET", "notifications/?limit=100", 200, token=token)
    return [item for item in result["items"] if item["article_id"] == article_id]


def delivered(cluster, article_id):
    identifier = str(UUID(article_id))
    return cluster.sql("article_db", "article_svc",
                       f"SELECT delivered_at IS NOT NULL FROM article_outbox WHERE article_id = '{identifier}'")


def restart_stateful(cluster, name):
    cluster.scale("statefulset/" + name, 1)
    cluster.rollout("statefulset/" + name)


def wait_backend(cluster, name):
    wait_until(lambda: cluster.endpoints(name), description=f"{name} Ready endpoint")


def test_deployment_storage_and_apis(cluster, client):
    for service in SERVICES:
        assert len(cluster.endpoints(service)) == 1
        api(client, "GET", f"{service}/health", 200)
        api(client, "GET", f"{service}/ready", 200)
        schema = api(client, "GET", f"{service}/openapi.json", 200)
        assert all(not path.startswith("/internal") for path in schema["paths"])
        api(client, "GET", f"{service}/internal/v1/health", 404)
        response = client.get(f"/api/v1/{service}/docs")
        assert response.status_code == 200 and "./openapi.json" in response.text
        assert "(head)" in cluster.run("exec", f"deployment/{service}", "--", "alembic", "current", "--check-heads")

    for component in ("postgres", "rabbitmq"):
        cluster.component_snapshot(component)
    postgres_audit = (ROOT / "tests/postgres-smoke.sh").read_text(encoding="utf-8").encode()
    output = cluster.run("exec", "-i", "postgres-0", "--", "bash", "-s", "--", "isolation",
                         "smoke_00000000000000000000000000000000", stdin=postgres_audit)
    assert output.count("(UTF-8, isolated)") == 6
    api(client, "GET", "auth/me", 401)
    categories = api(client, "GET", "articles/categories", 200)
    assert len(categories) == 7
    for path in ("/", "/admin/", "/register", "/login", "/profile"):
        response = client.get(path)
        assert response.status_code == 200 and "text/html" in response.headers["content-type"]
        assert "script-src 'self'" in response.headers["content-security-policy"]


def test_ingress_rejects_an_unlabelled_peer(cluster, client):
    api(client, "GET", "community/health", 200)
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"namespace": NAMESPACE, "generateName": "lab3-ingress-check-"},
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "containers": [{
                "name": "client", "image": "cybernews/auth:lab3", "imagePullPolicy": "Never",
                "command": ["python", "-c", "import time; time.sleep(100)"],
                "resources": {"requests": {"cpu": "25m", "memory": "32Mi"},
                              "limits": {"cpu": "150m", "memory": "96Mi"}},
            }],
        },
    }
    name = cluster.run("create", "-f", "-", "-o", "name", stdin=json.dumps(pod).encode())
    try:
        cluster.run("wait", name, "--for=condition=ready", "--timeout=60s")
        probe = ("import socket\n"
                 "for host, port in [('community', 8000), ('postgres', 5432), ('rabbitmq', 5672)]:\n"
                 " socket.getaddrinfo(host, port)\n"
                 " try:\n"
                 "  with socket.create_connection((host, port), timeout=3): print(host, 'connected')\n"
                 " except TimeoutError: print(host, 'blocked')")
        assert set(cluster.run("exec", name, "--", "python", "-c", probe).splitlines()) == {
            "community blocked", "postgres blocked", "rabbitmq blocked",
        }
        api(client, "GET", "community/health", 200)
    finally:
        cluster.run("delete", name, "--wait=false")


def test_auth_moderation_and_first_publication(cluster, client, admin):
    profile, _, reader = create_user(client)
    moderator, mod_password, _ = create_user(client)
    assert api(client, "GET", "auth/me", 200, token=reader)["id"] == profile["id"]
    api(client, "PATCH", f"auth/admin/users/{moderator['id']}/role", 200, token=admin, data={"role": "moderator"})
    mod = log_in(client, moderator["email"], mod_password)
    admin_password = secrets.token_urlsafe(24)
    api(client, "PUT", "auth/admin/password", 204, token=mod,
        data={"current_password": mod_password, "admin_password": admin_password})
    elevated = elevate(client, mod, admin_password)
    api(client, "GET", "collector/sources", 403, token=elevated)

    api(client, "PUT", "notifications/subscriptions/research", 200, token=reader)
    story = publish(client, admin)
    article_id = story["id"]
    post = f"community/articles/{article_id}/comments"
    comment = api(client, "POST", post, 201, token=reader, data={"body": "Lab 3 category update"})
    api(client, "PUT", f"community/articles/{article_id}/reaction", 200, token=reader, data={"reaction": "like"})
    api(client, "PUT", f"community/articles/{article_id}/bookmark", 200, token=reader)
    assert api(client, "GET", "community/bookmarks", 200, token=reader)[0]["article_id"] == article_id
    assert api(client, "GET", "community/bookmarks", 200, token=mod) == []
    api(client, "PATCH", f"community/comments/{comment['id']}", 403, token=mod, data={"body": "no access"})
    edited = api(client, "PATCH", f"community/comments/{comment['id']}", 200, token=reader,
                 data={"body": "Edited Lab 3 category update"})
    assert edited["body"] == "Edited Lab 3 category update"
    report = api(client, "POST", "moderation/reports", 201, token=reader,
                 data={"target_type": "article", "target_id": article_id, "reason": "Lab 3 moderation review"})
    api(client, "PATCH", f"moderation/reports/{report['id']}", 200, token=elevated, data={"status": "reviewed"})
    moderate = f"moderation/comments/{comment['id']}"
    api(client, "POST", moderate + "/hide", 200, token=elevated, data={"reason": "Lab 3 hide check"})
    api(client, "POST", moderate + "/restore", 403, token=elevated, data={"reason": "Lab 3 RBAC check"})
    api(client, "POST", moderate + "/restore", 200, token=admin, data={"reason": "Lab 3 restore check"})
    assert api(client, "GET", post, 200)["total"] == 1
    restriction = api(client, "POST", "moderation/restrictions", 201, token=elevated,
                      data={"user_id": profile["id"], "reason": "Lab 3 permission check"})
    api(client, "POST", post, 403, token=reader, data={"body": "Blocked comment"})
    lift = f"moderation/restrictions/{restriction['id']}/lift"
    api(client, "POST", lift, 403, token=elevated, data={"reason": "Lab 3 RBAC check"})
    assert not api(client, "POST", lift, 200, token=admin, data={"reason": "Lab 3 review"})["active"]
    api(client, "POST", post, 201, token=reader, data={"body": "Posting resumed after review"})
    api(client, "DELETE", f"community/comments/{comment['id']}", 204, token=reader)
    assert all(row["id"] != comment["id"] for row in api(client, "GET", post, 200)["items"])
    rows = wait_until(lambda: notifications(client, reader, article_id), description="first publication notification")
    assert len(rows) == 1 and rows[0]["available"] and not rows[0]["read"]
    api(client, "PATCH", f"notifications/{rows[0]['id']}/read", 404, token=mod)
    api(client, "PATCH", f"notifications/{rows[0]['id']}/read", 204, token=reader)
    assert notifications(client, reader, article_id)[0]["read"]
    wait_until(lambda: delivered(cluster, article_id) == "t", description="confirmed outbox row")


def test_community_has_shared_state_at_three_replicas(cluster, client, admin):
    _, _, token = create_user(client)
    story = publish(client, admin)
    article_id = story["id"]
    comments = f"community/articles/{article_id}/comments"
    reaction = f"community/articles/{article_id}/reaction"
    comment = api(client, "POST", comments, 201, token=token, data={"body": "Shared across replicas"})
    original = cluster.get("deployment", "community")["spec"]["replicas"]
    try:
        cluster.scale("deployment/community", 3)
        up = wait_until(lambda: nodes if len(nodes := cluster.endpoints("community")) == 3 else None,
                        description="three Community EndpointSlice targets")
        assert len(up) == 3

        def react(_):
            return api(client, "PUT", reaction, 200, token=token, data={"reaction": "like"})

        with ThreadPoolExecutor(max_workers=5) as threads:
            assert all(result["my_reaction"] == "like" for result in threads.map(react, range(12)))
        assert api(client, "GET", reaction + "s", 200, token=token)["likes"] == 1
        removed = sorted(up)[0]
        cluster.run("delete", "pod", removed, "--wait=false")
        assert api(client, "GET", comments, 200)["items"][0]["id"] == comment["id"]
        replacement = wait_until(lambda: nodes if len(nodes := cluster.endpoints("community")) == 3 and removed not in nodes else None,
                                 description="replacement Community Pod")
        assert len(replacement - up) == 1
        print(f"Community 1 to 3: removed {removed}, replaced by {next(iter(replacement - up))}")
        assert api(client, "GET", reaction + "s", 200, token=token)["likes"] == 1
    finally:
        cluster.scale("deployment/community", original)
        wait_until(lambda: len(cluster.endpoints("community")) == original, description="original Community scale")


def test_postgres_pvc_and_readiness_after_outage(cluster, client, admin):
    profile, _, user = create_user(client)
    story = publish(client, admin)
    comments = f"community/articles/{story['id']}/comments"
    comment = api(client, "POST", comments, 201, token=user, data={"body": "Retained on PostgreSQL PVC"})
    old = cluster.component_snapshot("postgres")
    article_pod = next(iter(cluster.endpoints("articles")))
    count = cluster.get("pod", article_pod)["status"]["containerStatuses"][0]["restartCount"]
    probe = ("from urllib.request import urlopen; from urllib.error import HTTPError\n"
             "for path in ('health', 'ready'):\n"
             " try: print(path, urlopen('http://127.0.0.1:8000/'+path,timeout=10).status)\n"
             " except HTTPError as e: print(path, e.code)")

    cluster.scale("statefulset/postgres", 0)
    try:
        cluster.run("wait", "--for=delete", "pod/postgres-0", "--timeout=120s")
        output = cluster.run("exec", article_pod, "--", "python", "-c", probe)
        assert {"health 200", "ready 503"}.issubset(output.splitlines())
        wait_until(lambda: not cluster.endpoints("articles"), description="Articles removed from Ready endpoints")
        assert cluster.get("pvc", "postgres-data")["metadata"]["uid"] == old[1]
    finally:
        restart_stateful(cluster, "postgres")
        for service in SERVICES:
            wait_backend(cluster, service)
    new = cluster.component_snapshot("postgres")
    assert old[0] != new[0] and old[1:] == new[1:]
    assert cluster.get("pod", article_pod)["status"]["containerStatuses"][0]["restartCount"] == count
    assert api(client, "GET", "auth/me", 200, token=user)["id"] == profile["id"]
    assert api(client, "GET", "articles/" + story["id"], 200)["title"] == story["title"]
    assert api(client, "GET", comments, 200)["items"][0]["id"] == comment["id"]
    print(f"PostgreSQL replaced: {old[0]} -> {new[0]}, PV retained: {new[2]}; probes 200/503 then Ready")


def queued_messages(cluster):
    rows = cluster.run("exec", "rabbitmq-0", "--", "rabbitmqctl", "-q", "list_queues", "-p", "cybernews",
                       "name", "messages_ready", "durable")
    for row in rows.splitlines():
        fields = row.split()
        if fields and fields[0] == "cybernews.notifications.article-published.v1":
            assert fields[2] == "true"
            return int(fields[1])
    return 0


def test_rabbitmq_retains_queue_and_replays_outbox(cluster, client, admin):
    _, _, reader = create_user(client)
    api(client, "PUT", "notifications/subscriptions/other", 200, token=reader)
    old = cluster.component_snapshot("rabbitmq")
    cluster.scale("deployment/notifications", 0)
    try:
        wait_until(lambda: not cluster.endpoints("notifications"), description="Notifications stopped")
        queued = publish(client, admin, "other")
        wait_until(lambda: delivered(cluster, queued["id"]) == "t", description="publisher confirmation")
        wait_until(lambda: queued_messages(cluster) >= 1, description="durable queued event")
        cluster.scale("statefulset/rabbitmq", 0)
        try:
            cluster.run("wait", "--for=delete", "pod/rabbitmq-0", "--timeout=120s")
            pending = publish(client, admin, "other")
            assert delivered(cluster, pending["id"]) == "f"
            assert cluster.get("pvc", "rabbitmq-data")["metadata"]["uid"] == old[1]
        finally:
            restart_stateful(cluster, "rabbitmq")
        new = cluster.component_snapshot("rabbitmq")
        assert old[0] != new[0] and old[1:] == new[1:]
        wait_until(lambda: queued_messages(cluster) >= 2, description="retained event and replayed outbox")
    finally:
        cluster.scale("deployment/notifications", 1)
        cluster.rollout("deployment/notifications")
    wait_until(lambda: client.get("/api/v1/notifications/ready").status_code == 200,
               description="Notifications ready through the Gateway")
    for story in queued, pending:
        rows = wait_until(lambda: notifications(client, reader, story["id"]), description="notification after broker recovery")
        assert len(rows) == 1
        assert delivered(cluster, story["id"]) == "t"
    queue_info = cluster.run("exec", "rabbitmq-0", "--", "rabbitmqctl", "-q", "list_queues", "-p", "cybernews",
                             "name", "type", "durable")
    assert re.search(r"cybernews\.notifications\.article-published\.v1\s+quorum\s+true", queue_info)
    assert re.search(r"cybernews\.notifications\.dead\.v1\s+classic\s+true", queue_info)
    print(f"RabbitMQ replaced: {old[0]} -> {new[0]}, PV retained: {new[2]}; two notifications delivered exactly once")


def test_browser_on_kubernetes(open_page, origin, client, admin, admin_credentials):
    story = publish(client, admin)
    desktop = open_page(origin)
    route(desktop, "/")
    browser_expect(heading(desktop, "Cybersecurity news")).to_be_visible()
    browser_expect(desktop.locator("html")).to_have_attribute("data-theme", "light")
    desktop.locator("#feed-query").fill(story["title"].split()[-1])
    browser_expect(story_link(desktop, story["title"])).to_be_visible()
    desktop.locator(".category-links").get_by_role("link", name="Research", exact=True).click()
    browser_expect(desktop).to_have_url(re.compile("category=research"))
    browser_expect(story_link(desktop, story["title"])).to_be_visible()

    sources = api(client, "GET", "articles/sources", 200)
    assert sources, "Sync the Lab 3 RSS sources before checking publisher links and source filters"
    source = sources[0]
    source_stories = api(client, "GET", f"articles/?source_id={source['id']}&sort=oldest&limit=1", 200)
    external = source_stories["items"][0]
    route(desktop, "/")
    desktop.locator(".filters summary").click()
    desktop.locator('[name="source_id"]').select_option(source["id"])
    desktop.locator('[name="sort"]').select_option("oldest")
    desktop.get_by_role("button", name="Apply", exact=True).click()
    browser_expect(desktop).to_have_url(re.compile("source_id=" + source["id"]))
    browser_expect(story_link(desktop, external["title"])).to_be_visible()
    route(desktop, "/article/" + external["id"])
    browser_expect(heading(desktop, external["title"])).to_be_visible()
    browser_expect(story_link(desktop, "Read the story on the publisher’s website")).to_have_attribute(
        "href", external["original_url"],
    )
    desktop.get_by_role("button", name="Theme", exact=True).click()
    desktop.get_by_role("dialog").get_by_role("combobox", name="Theme", exact=True).select_option("dark")
    desktop.keyboard.press("Escape")
    browser_expect(desktop.locator("html")).to_have_attribute("data-theme", "dark")
    desktop.get_by_role("button", name="Interface language · RU").click()
    browser_expect(desktop.locator("html")).to_have_attribute("lang", "ru")
    route(desktop, "/")
    browser_expect(heading(desktop, "Новости кибербезопасности")).to_be_visible()

    page = open_page(origin, width=390, mobile=True)
    route(page, "/")
    browser_expect(heading(page, "Cybersecurity news")).to_be_visible()
    browser_expect(page.locator(".hero h2")).to_be_visible()
    capture(page, "lab3-kubernetes-mobile")

    email, password, elevation = admin_credentials
    signin(page, email, password, "/admin/")
    unlock(page, elevation)
    browser_expect(heading(page, "Overview")).to_be_visible()
    route(page, "/article/" + story["id"])
    browser_expect(heading(page, story["title"])).to_be_visible()
    browser_expect(page.get_by_text("Kubernetes integration record", exact=True)).to_be_visible()
    page.reload()
    browser_expect(heading(page, story["title"])).to_be_visible()

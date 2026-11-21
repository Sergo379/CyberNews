"""Browser tests against Nginx and real services, with a read-only live check."""

import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

ARTIFACTS = Path(".test-artifacts/stage5")
expect.set_options(timeout=12000)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        channel = os.getenv("CYBERNEWS_BROWSER_CHANNEL")
        engine = os.getenv("CYBERNEWS_BROWSER_ENGINE", "chromium")
        browser_type = getattr(playwright, engine)
        instance = browser_type.launch(**({"channel": channel} if channel else {}))
        yield instance
        instance.close()


@pytest.fixture
def isolated():
    url = os.getenv("CYBERNEWS_TEST_BASE_URL", "")
    parsed = urlsplit(url)
    if not os.getenv("CYBERNEWS_TEST_PROJECT", "").startswith("cybernews-stage5-"):
        pytest.skip("Run with scripts/smoke-test-stage5.ps1")
    assert parsed.hostname == "127.0.0.1" and parsed.port not in (None, 8080)
    return url


@pytest.fixture
def open_page(browser):
    contexts = []

    def create(url, width=1440, mobile=False):
        context = browser.new_context(
            base_url=url, locale="en-US", color_scheme="light", viewport={"width": width, "height": 900},
            is_mobile=mobile and browser.browser_type.name != "firefox", has_touch=mobile,
        )
        context.add_init_script("""
            localStorage.setItem("cybernews.lang", localStorage.getItem("cybernews.lang") || "en");
            globalThis.cspViolations = [];
            document.addEventListener("securitypolicyviolation", event =>
                globalThis.cspViolations.push([event.violatedDirective, event.blockedURI, event.sourceFile]));
        """)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        contexts.append((context, page, errors))
        return page
    yield create
    issues = []
    for context, page, errors in contexts:
        issues.extend(errors)
        issues.extend(page.evaluate("globalThis.cspViolations || []"))
        context.close()
    assert not issues


def capture(page, name):
    if page.context.browser.browser_type.name == "webkit":
        # Playwright's WebKit screenshot injects a stylesheet, which the site's CSP blocks.
        return
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=ARTIFACTS / (name + ".png"), caret="initial")


def call(client, verb, path, status, data=None, headers=None):
    kwargs = {"headers": headers} if headers else {}
    if data is not None:
        kwargs["json"] = data
    response = client.request(verb, "/api/v1/" + path, **kwargs)
    assert response.status_code == status, path + " returned " + str(response.status_code)
    return response.json() if response.content and status < 400 else None


def new_account(client, prefix):
    account = {
        "email": prefix + "-" + secrets.token_hex(4) + "@example.com",
        "nickname": prefix + "-" + secrets.token_hex(4),
        "password": secrets.token_urlsafe(22),
    }
    person = call(client, "POST", "auth/register", 201, account)
    return account, person


def root_details():
    return (os.environ["CYBERNEWS_TEST_SUPER_EMAIL"], os.environ["CYBERNEWS_TEST_SUPER_PASSWORD"],
            os.environ["CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD"])


def headers_for(client, email, password, elevated=None):
    login = call(client, "POST", "auth/login", 200, {"email": email, "password": password})
    headers = {"Authorization": "Bearer " + login["access_token"]}
    if elevated:
        session = call(client, "POST", "auth/admin/unlock", 200, {"admin_password": elevated}, headers)
        headers["X-Admin-Session"] = session["admin_session"]
    return headers


def route(page, path):
    response = page.goto(path, wait_until="domcontentloaded")
    assert response.status == 304 or (response.ok and "text/html" in response.headers.get("content-type", "")), (
        path, response.status,
    )


def heading(page, name):
    return page.get_by_role("heading", name=name, exact=True)


def fill(page, name, value):
    page.locator(f'[name="{name}"]').filter(visible=True).fill(value)


def submit(page, form, label=None):
    target = page.locator(f'[data-form="{form}"]')
    target.get_by_role("button", name=label, exact=True).click() if label else target.locator('[type="submit"]').click()


def signin(page, email, password, next_="/profile"):
    route(page, "/login?next=" + next_)
    fill(page, "email", email)
    fill(page, "password", password)
    submit(page, "login")
    expect(page).to_have_url(re.compile(re.escape(next_) + "$"))


def unlock(page, secret):
    expect(heading(page, "Unlock admin access")).to_be_visible()
    fill(page, "admin_password", secret)
    submit(page, "admin-unlock")
    expect(page.locator(".sidebar-nav")).to_be_visible()


def navigate_admin(page, label):
    page.locator(".sidebar-nav").get_by_role("link", name=label, exact=True).click()
    expect(page.locator(".admin-work").get_by_role("heading", name=label, exact=True)).to_be_visible()


def story_link(page, title):
    return page.get_by_role("link", name=title, exact=True)


def count_value(page, name):
    return page.get_by_role("button", name=name, exact=True)


def wait_for_publication_event(page, article_id):
    token = page.evaluate("sessionStorage.getItem('cybernews.access')")
    until = monotonic() + 18
    while monotonic() < until:
        response = page.request.get("/api/v1/notifications/?unread=true", headers={"Authorization": "Bearer " + token})
        assert response.ok
        if any(item["article_id"] == article_id for item in response.json()["items"]):
            return
        sleep(0.25)
    pytest.fail("The browser subscription did not receive the publication event")


def test_live_catalog_and_responsive(open_page):
    origin = os.getenv("CYBERNEWS_LIVE_READONLY_URL")
    if not origin:
        pytest.skip("Set CYBERNEWS_LIVE_READONLY_URL for the read-only check")
    page = open_page(origin)
    data = page.request.get("/api/v1/articles/?limit=9").json()
    assert data["total"] > 0
    route(page, "/")
    expect(heading(page, "Cybersecurity news")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    expect(page.locator(".hero .hero-art")).to_be_visible()
    expect(page.locator(".news-card")).to_have_count(len(data["items"]) - 1)
    expect(story_link(page, data["items"][0]["title"])).to_be_visible()
    capture(page, "catalog-en-light")
    if data["total"] > 9:
        next_count = min(9, data["total"] - 9)
        page.get_by_role("button", name="Next", exact=True).click()
        expect(page).to_have_url(re.compile("offset=9"))
        expect(page.locator(".news-card")).to_have_count(next_count)
        page.go_back()
        expect(page.locator(".hero")).to_be_visible()
        page.go_forward()
        expect(page.locator(".news-card")).to_have_count(next_count)
    path = "/article/" + data["items"][0]["id"]
    route(page, path)
    expect(heading(page, data["items"][0]["title"])).to_be_visible()
    if data["items"][0]["original_url"]:
        expect(story_link(page, "Read the story on the publisher’s website")).to_have_attribute("href", re.compile("^https?://"))
    page.reload()
    expect(heading(page, data["items"][0]["title"])).to_be_visible()
    capture(page, "article-en-light")
    route(page, "/missing-page")
    expect(page.locator("h1")).to_have_text("Page not found")
    route(page, "/")
    expect(heading(page, "Cybersecurity news")).to_be_visible()
    page.get_by_role("button", name="Theme", exact=True).click()
    page.get_by_role("dialog").get_by_role("combobox", name="Theme", exact=True).select_option("dark")
    page.keyboard.press("Escape")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.get_by_role("button", name="Interface language · RU").click()
    expect(page.locator("html")).to_have_attribute("lang", "ru")
    expect(heading(page, "Новости кибербезопасности")).to_be_visible()
    expect(page.locator(".hero")).to_be_visible()
    capture(page, "catalog-ru-dark")
    for width in (360, 375, 390, 430, 768, 1024, 1280, 1920, 2560):
        page.set_viewport_size({"width": width, "height": 880})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        if width in (360, 390, 768, 1920):
            capture(page, f"catalog-{width}")
    small = open_page(origin, width=390, mobile=True)
    route(small, "/")
    expect(heading(small, "Cybersecurity news")).to_be_visible()
    small.emulate_media(color_scheme="dark")
    expect(small.locator("html")).to_have_attribute("data-theme", "dark")
    small.keyboard.press("Tab")
    expect(small.get_by_text("Skip to content")).to_be_focused()
    small.keyboard.press("Enter")
    expect(small.locator("main")).to_be_focused()
    small.get_by_role("button", name="Open menu").click()
    small.get_by_role("dialog").get_by_role("link", name="Register", exact=True).click()
    expect(heading(small, "Create an account")).to_be_visible()
    fill(small, "email", "browser@example.com")
    fill(small, "nickname", "Browser Preview")
    expect(small.locator('[name="email"]')).to_have_value("browser@example.com")
    capture(small, "register-mobile")
    route(small, "/login")
    expect(heading(small, "Sign in to CyberNews")).to_be_visible()
    capture(small, "login-mobile")
    assert small.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_catalog_search_external_and_errors(isolated, open_page):
    page = open_page(isolated)
    route(page, "/")
    query = page.locator("#feed-query")
    expect(query).to_be_visible()
    page.wait_for_function("""async () => {
        const response = await fetch("/api/v1/articles/?q=acorn");
        return response.ok && (await response.json()).total > 0;
    }""")
    query.fill("Acorn")
    expect(story_link(page, "Acorn vulnerability check")).to_be_visible()
    expect(page).to_have_url(re.compile(r"q=Acorn"))
    page.locator(".category-links").get_by_role("link", name="Vulnerabilities", exact=True).click()
    expect(page).to_have_url(re.compile("category=vulnerabilities"))
    expect(story_link(page, "Acorn vulnerability check")).to_be_visible()
    response = page.request.get("/api/v1/articles/?q=Acorn").json()["items"][0]
    page.locator(".filters summary").click()
    page.locator('[name="sort"]').select_option("oldest")
    fill(page, "from", "2026-11-01")
    fill(page, "to", "2026-11-30")
    sources = page.locator('[name="source_id"] option').evaluate_all("(options) => options.map(option => option.value)")
    assert len(sources) > 1
    assert response["source_id"] in sources
    page.locator('[name="source_id"]').select_option(response["source_id"])
    page.get_by_role("button", name="Apply", exact=True).click()
    expect(page).to_have_url(re.compile(r"sort=oldest"))
    expect(story_link(page, "Acorn vulnerability check")).to_be_visible()
    route(page, "/article/" + response["id"])
    expect(heading(page, "Acorn vulnerability check")).to_be_visible()
    expect(story_link(page, "Read the story on the publisher’s website")).to_have_attribute("rel", "noopener noreferrer")
    expect(page.locator(".prose")).to_have_count(0)
    expect(page.locator(".lead-image")).to_have_count(0)
    count_value(page, "Like").click()
    expect(heading(page, "Sign in to continue")).to_be_visible()
    page.keyboard.press("Escape")
    route(page, "/profile")
    expect(heading(page, "Sign in to CyberNews")).to_be_visible()
    assert "/login?next=%2Fprofile" in page.url
    birch = page.request.get("/api/v1/articles/?q=Birch").json()["items"][0]
    route(page, "/article/" + birch["id"])
    expect(page.get_by_text("Publication date unavailable", exact=True)).to_be_visible()

    page.route("**/api/v1/articles/?*", lambda request: request.fulfill(status=503, content_type="application/json", body="{}"))
    route(page, "/")
    expect(heading(page, "Could not load")).to_be_visible()
    page.unroute("**/api/v1/articles/?*")
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.locator(".hero")).to_be_visible()
    assert page.request.get("/api/v1/auth/internal/v1/me").status == 404
    assert page.request.get("/api/v1/unknown/resource").status == 404


def test_account_community_and_notifications(isolated, open_page):
    page = open_page(isolated, width=390, mobile=True)
    with httpx.Client(base_url=isolated, timeout=12) as client:
        root = headers_for(client, *root_details())
        suffix = secrets.token_hex(4)
        story = call(client, "POST", "articles/admin/articles", 201, {
            "title": "Original coverage " + suffix, "category": "research", "content": "<h2>Original section</h2><p>Real sandbox content</p>",
            "status": "published",
        }, root)
        path = "/article/" + story["id"]
        email = "reader-" + suffix + "@example.com"
        password = secrets.token_urlsafe(22)
        updated_password = secrets.token_urlsafe(22)
        route(page, "/register")
        for key, value in {"email": email, "nickname": "reader-" + suffix, "password": password,
                           "confirm_password": password}.items():
            fill(page, key, value)
        submit(page, "register")
        expect(heading(page, "Sign in to CyberNews")).to_be_visible()
        signin(page, email, password)
        expect(heading(page, "Profile")).to_be_visible()
        fill(page, "nickname", "reader-update-" + suffix)
        changed_email = "updated-" + suffix + "@example.com"
        fill(page, "email", changed_email)
        submit(page, "profile")
        expect(heading(page, "reader-update-" + suffix)).to_be_visible()
        expect(page.locator('[name="email"]')).to_have_value(changed_email)
        capture(page, "profile-mobile")
        route(page, "/admin/")
        expect(heading(page, "Admin access required")).to_be_visible()
        route(page, path)
        expect(heading(page, "Original section")).to_be_visible()
        expect(page.locator(".original-note")).to_have_count(0)
        like = count_value(page, "Like")
        dislike = count_value(page, "Dislike")
        like.click()
        expect(like).to_have_attribute("aria-pressed", "true")
        dislike.click()
        expect(like).to_have_attribute("aria-pressed", "false")
        expect(dislike).to_have_attribute("aria-pressed", "true")
        dislike.click()
        expect(dislike).to_have_attribute("aria-pressed", "false")
        page.get_by_role("button", name="Save story", exact=True).click()
        expect(page.get_by_role("button", name="Remove saved story")).to_be_visible()
        fill(page, "body", "Community comment <strong>still plain</strong>")
        submit(page, "comment")
        row = page.locator(".comment-item")
        expect(row.locator(".comment-text")).to_have_text("Community comment still plain")
        expect(row.locator(".comment-text strong")).to_have_count(0)
        row.get_by_role("button", name="Like", exact=True).click()
        expect(row.get_by_role("button", name="Like", exact=True)).to_have_attribute("aria-pressed", "true")
        row.get_by_role("button", name="Edit", exact=True).click()
        page.get_by_role("dialog").locator('[name="body"]').fill("Updated comment")
        submit(page, "edit-comment")
        expect(row.get_by_text("Updated comment")).to_be_visible()
        row.get_by_role("button", name="Delete", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Delete", exact=True).click()
        expect(heading(page, "No comments yet")).to_be_visible()
        page.get_by_role("button", name="Report story").click()
        fill(page, "reason", "Please verify source")
        fill(page, "description", "Browser-owned isolated report")
        submit(page, "report")
        expect(page.get_by_text("Report sent.")).to_be_visible()
        route(page, "/bookmarks")
        expect(story_link(page, story["title"])).to_be_visible()
        capture(page, "bookmarks-mobile")
        route(page, "/subscriptions")
        page.get_by_role("button", name="Subscribe · Research", exact=True).click()
        expect(page.get_by_role("button", name="Unsubscribe · Research", exact=True)).to_be_visible()
        notification = call(client, "POST", "articles/admin/articles", 201, {
            "title": "Notification " + suffix, "category": "research", "content": "<p>Publication event</p>", "status": "published",
        }, root)
        wait_for_publication_event(page, notification["id"])
        route(page, "/notifications?unread=true")
        expect(heading(page, notification["title"])).to_be_visible()
        expect(page.locator(".notif-count")).to_have_text("1")
        capture(page, "notifications-mobile")
        page.get_by_role("button", name="Open story", exact=True).click()
        expect(heading(page, notification["title"])).to_be_visible()
        route(page, "/notifications?unread=true")
        expect(heading(page, "No unread notifications")).to_be_visible()
        call(client, "POST", "articles/admin/articles/" + notification["id"] + "/hide", 200, headers=root)
        route(page, "/notifications")
        expect(heading(page, "Story unavailable")).to_be_visible()
        expect(heading(page, notification["title"])).to_have_count(0)
        assert notification["id"] not in page.locator("main").inner_html()
        route(page, "/bookmarks")
        page.get_by_role("button", name="Remove saved story", exact=True).click()
        expect(heading(page, "No saved stories")).to_be_visible()
        route(page, "/profile")
        assert page.evaluate("Object.keys(localStorage).every(key => !/access|password|token/i.test(key))")
        old_token = page.evaluate("sessionStorage.getItem('cybernews.access')")
        fill(page, "current_password", password)
        fill(page, "new_password", updated_password)
        fill(page, "confirm_password", updated_password)
        submit(page, "password")
        expect(heading(page, "Sign in to CyberNews")).to_be_visible()
        call(client, "GET", "auth/me", 401, headers={"Authorization": "Bearer " + old_token})
        signin(page, changed_email, updated_password)
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(heading(page, "Cybersecurity news")).to_be_visible()
        assert page.evaluate("sessionStorage.getItem('cybernews.access')") is None
        signin(page, changed_email, updated_password)
        page.clock.install()
        page.clock.fast_forward(910000)
        expect(heading(page, "Sign in to CyberNews")).to_be_visible()
        assert page.evaluate("sessionStorage.getItem('cybernews.access')") is None
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_moderator_permissions_and_review(isolated, open_page):
    page = open_page(isolated)
    with httpx.Client(base_url=isolated, timeout=12) as client:
        super_admin = headers_for(client, *root_details())
        moderator, mod = new_account(client, "moderator")
        regular, target = new_account(client, "ordinary")
        other, _ = new_account(client, "reporter")
        role = "auth/admin/users/" + mod["id"] + "/role"
        call(client, "PATCH", role, 200, {"role": "moderator"}, super_admin)
        article = call(client, "POST", "articles/admin/articles", 201, {
            "title": "Moderator browser checks", "content": "<p>Story content</p>", "status": "published",
        }, super_admin)
        article_path = "community/articles/" + article["id"] + "/comments"
        regular_headers = headers_for(client, regular["email"], regular["password"])
        other_headers = headers_for(client, other["email"], other["password"])
        comment = call(client, "POST", article_path, 201, {"body": "Isolated moderation queue"}, regular_headers)
        report = call(client, "POST", "moderation/reports", 201, {
            "target_type": "comment", "target_id": comment["id"], "reason": "Browser moderation review",
        }, other_headers)
        signin(page, moderator["email"], moderator["password"], "/admin/")
        expect(heading(page, "Unlock admin access")).to_be_visible()
        expect(page.locator(".sidebar-nav")).to_have_count(0)
        capture(page, "admin-unlock")
        page.get_by_role("button", name="Set admin password", exact=True).click()
        fill(page, "current_password", moderator["password"])
        separate = secrets.token_urlsafe(22)
        panel = page.get_by_role("dialog")
        panel.locator('[name="admin_password"]').fill(separate)
        submit(page, "admin-password")
        expect(panel).to_have_count(0)
        unlock(page, separate)
        expect(page.locator(".sidebar-nav").get_by_role("link")).to_have_count(5)
        for label in ("Users", "RSS sources", "News"):
            expect(page.locator(".sidebar-nav").get_by_role("link", name=label, exact=True)).to_have_count(0)
        token = page.evaluate("sessionStorage.getItem('cybernews.access')")
        ordinary_admin = {"Authorization": "Bearer " + token}
        call(client, "GET", "auth/admin/user-search?q=ordinary", 403, headers=ordinary_admin)
        moderator_admin = headers_for(client, moderator["email"], moderator["password"], separate)
        call(client, "GET", "auth/admin/users", 403, headers=moderator_admin)
        call(client, "GET", "auth/admin/user-search?q=ordinary", 401)
        lookup = call(client, "GET", "auth/admin/user-search?q=" + regular["nickname"], 200, headers=moderator_admin)
        assert lookup == [{"id": target["id"], "nickname": regular["nickname"]}]
        assert call(client, "GET", "auth/admin/user-search?user_id=" + mod["id"], 200, headers=moderator_admin) == []
        navigate_admin(page, "Reports")
        row = page.get_by_role("row").filter(has_text="Browser moderation review")
        row.get_by_role("button", name="Details").click()
        panel = page.get_by_role("dialog")
        panel.get_by_role("button", name="Mark reviewed").click()
        fill(page, "reason", "Handled in browser")
        submit(page, "mark_reviewed")
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert call(client, "GET", "moderation/reports/" + report["id"], 200, headers=moderator_admin)["status"] == "reviewed"
        navigate_admin(page, "Comments")
        page.get_by_role("row").filter(has_text="Isolated moderation queue").get_by_role("button", name="Details").click()
        panel = page.get_by_role("dialog")
        expect(panel.get_by_text(target["nickname"], exact=True)).to_be_visible()
        panel.get_by_role("button", name="Hide comment", exact=True).click()
        fill(page, "reason", "Browser command")
        submit(page, "hide_comment")
        expect(page.get_by_role("row").filter(has_text="Isolated moderation queue")).to_contain_text("Hidden")
        navigate_admin(page, "Restrictions")
        fill(page, "q", regular["nickname"])
        submit(page, "find-user")
        page.get_by_role("row").filter(has_text=regular["nickname"]).get_by_role("button", name="Restrict commenting").click()
        fill(page, "reason", "Browser restriction")
        submit(page, "restriction_place")
        expect(page.get_by_role("row").filter(has_text="Browser restriction")).to_be_visible()
        expect(page.get_by_role("button", name="Lift restriction")).to_have_count(0)
        expect(page.get_by_role("button", name="Restore comment")).to_have_count(0)
        reader = open_page(isolated)
        signin(reader, regular["email"], regular["password"], "/article/" + article["id"])
        expect(reader.get_by_text("Commenting has been restricted by an administrator.")).to_be_visible()
        expect(reader.get_by_role("button", name="Post comment")).to_have_count(0)
        assert call(client, "GET", article_path, 200)["total"] == 0
        navigate_admin(page, "Audit")
        expect(page.get_by_role("cell", name="Commenting restricted", exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 880})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        capture(page, "moderator-audit-mobile")
        page.reload()
        expect(heading(page, "Unlock admin access")).to_be_visible()
        assert page.evaluate("Object.keys(sessionStorage)") == ["cybernews.access"]
        unlock(page, separate)
        page.clock.install(time=datetime.now(timezone.utc) + timedelta(seconds=301))
        page.locator(".sidebar-nav").get_by_role("link", name="Reports", exact=True).click()
        expect(heading(page, "Unlock admin access")).to_be_visible()
        expect(page.locator(".sidebar-nav")).to_have_count(0)
        assert page.evaluate("Object.keys(localStorage).every(key => !/admin|password|token/i.test(key))")


def test_super_admin_editorial_rss_and_audit(isolated, open_page):
    page = open_page(isolated)
    email, password, secret = root_details()
    with httpx.Client(base_url=isolated, timeout=12) as client:
        elevated = headers_for(client, email, password, secret)
        account, target = new_account(client, "managed")
        call(client, "POST", "moderation/restrictions", 201, {
            "user_id": target["id"], "reason": "Browser restriction to lift",
        }, elevated)
        signin(page, email, password, "/admin/")
        unlock(page, secret)
        expect(heading(page, "Overview")).to_be_visible()
        expect(page.get_by_text("Published stories", exact=True)).to_be_visible()
        capture(page, "admin-desktop-overview")
        navigate_admin(page, "Users")
        user_row = page.get_by_role("row").filter(has_text=account["nickname"])
        user_row.get_by_role("button", name="Change role", exact=True).click()
        expect(page.get_by_text("The user must sign in again after their role changes.")).to_be_visible()
        page.get_by_role("dialog").get_by_label("Role", exact=True).select_option("moderator")
        submit(page, "change-role")
        expect(user_row).to_contain_text("Moderator")
        user_row.get_by_role("button", name="Change role", exact=True).click()
        page.get_by_role("dialog").get_by_label("Role", exact=True).select_option("user")
        submit(page, "change-role")
        user_row.get_by_role("button", name="Suspend account", exact=True).click()
        fill(page, "reason", "Isolated account action")
        submit(page, "suspend")
        expect(user_row).to_contain_text("Suspended")
        assert call(client, "GET", "auth/admin/user-search?q=" + target["nickname"], 200, headers=elevated) == []
        assert call(client, "GET", "auth/admin/user-search?user_id=" + target["id"], 200, headers=elevated) == [
            {"id": target["id"], "nickname": target["nickname"]},
        ]
        user_row.get_by_role("button", name="Restore account", exact=True).click()
        fill(page, "reason", "Isolated account restoration")
        submit(page, "restore_account")
        expect(user_row).to_contain_text("Active")
        navigate_admin(page, "Restrictions")
        restriction_row = page.get_by_role("row").filter(has_text="Browser restriction to lift")
        restriction_row.get_by_role("button", name="Lift restriction").click()
        fill(page, "reason", "Isolated lift")
        submit(page, "restriction_lift")
        expect(restriction_row).to_contain_text("Lifted")
        navigate_admin(page, "News")
        page.get_by_role("button", name="New story", exact=True).click()
        title = "Edited through browser " + secrets.token_hex(4)
        fill(page, "title", title)
        fill(page, "summary", "Summary from the isolated editor")
        fill(page, "content", '<h2>Protected formatting</h2><p>Original text</p><script>throw Error("unsafe")</script>')
        page.get_by_text("Preview", exact=True).click()
        expect(heading(page, "Protected formatting")).to_be_visible()
        expect(page.get_by_role("dialog").locator("script")).to_have_count(0)
        capture(page, "admin-editor")
        submit(page, "editor")
        story_row = page.get_by_role("row").filter(has_text=title)
        expect(story_row).to_contain_text("Draft")
        story_row.get_by_role("button", name="Edit story", exact=True).click()
        fill(page, "author", "Editorial test")
        submit(page, "editor")
        story_row.get_by_role("button", name="Publish", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Publish", exact=True).click()
        expect(story_row).to_contain_text("Published")
        story_route = story_row.get_by_role("link", name=title).get_attribute("href")
        story_row.get_by_role("button", name="Hide story").click()
        page.get_by_role("dialog").get_by_role("button", name="Hide story").click()
        expect(story_row).to_contain_text("Hidden")
        story_row.get_by_role("button", name="Restore story").click()
        page.get_by_role("dialog").get_by_role("button", name="Restore story").click()
        expect(story_row).to_contain_text("Published")
        navigate_admin(page, "RSS sources")
        page.get_by_role("button", name="Add source", exact=True).click()
        source = "Test licensed feed " + secrets.token_hex(4)
        fill(page, "name", source)
        fill(page, "feed_url", "https://rss-fixture.example/licensed")
        fill(page, "website_url", "https://rss-fixture.example/")
        page.get_by_role("dialog").get_by_label("Publication policy").select_option("full_article")
        submit(page, "source-editor")
        expect(page.get_by_text("Enter a permission record to publish full text or images.")).to_be_visible()
        fill(page, "rights_reference", "Isolated fixture rights record")
        submit(page, "source-editor")
        source_row = page.get_by_role("row").filter(has_text=source)
        expect(source_row).to_be_visible()
        source_row.get_by_role("button", name="Disable", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Disable", exact=True).click()
        expect(source_row).to_contain_text("Inactive")
        source_row.get_by_role("button", name="Enable", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Enable", exact=True).click()
        source_row.get_by_role("button", name="Sync", exact=True).click()
        expect(heading(page, "Sync history")).to_be_visible()
        page.locator("tbody").get_by_role("button", name="Details").first.click()
        expect(heading(page, "Sync result")).to_be_visible()
        page.keyboard.press("Escape")
        navigate_admin(page, "Audit")
        page.get_by_label("Source", exact=True).select_option("articles")
        expect(page.get_by_role("cell", name="Story restored", exact=True)).to_be_visible()
        page.get_by_role("button", name="Lock admin access", exact=True).click()
        expect(heading(page, "Unlock admin access")).to_be_visible()
        route(page, story_route)
        expect(heading(page, "Protected formatting")).to_be_visible()
        expect(page.get_by_text("Editorial test", exact=False)).to_be_visible()

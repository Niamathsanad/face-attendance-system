"""Administrator login, sessions, CSRF, brute-force lock, unauthorised access."""
import pytest

from conftest import extract_csrf, login

PROTECTED_PAGES = ["/dashboard", "/students", "/students/register", "/students/1/enroll", "/sessions", "/live",
                   "/attendance", "/reports", "/reports/export?kind=day", "/audit", "/profile"]


def test_login_success_and_logout(client, db):
    db.execute("UPDATE administrators SET must_change_password=0"); db.commit()
    r = login(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302          # logged out again


def test_wrong_password_is_rejected(client):
    r = login(client, password="wrong")
    assert r.status_code == 401 and b"Invalid username or password" in r.data


def test_unknown_user_gives_same_message(client):
    r = login(client, username="nobody", password="whatever")
    assert r.status_code == 401 and b"Invalid username or password" in r.data


@pytest.mark.parametrize("url", PROTECTED_PAGES)
def test_pages_require_login(client, url):
    r = client.get(url)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


@pytest.mark.parametrize("method,url", [("post", "/api/recognize"), ("get", "/api/dashboard"), ("post", "/api/students/1/enroll")])
def test_api_returns_401_json_when_logged_out(client, method, url):
    r = getattr(client, method)(url, json={})
    assert r.status_code == 401 and r.get_json()["ok"] is False


@pytest.mark.parametrize("url", ["/students/1/delete", "/students/1/delete-biometrics", "/sessions/create",
                                 "/sessions/1/close", "/attendance/correct", "/profile/password"])
def test_post_actions_require_login(client, url):
    r = client.post(url, data={})
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_first_login_forces_password_change(client):
    login(client)
    r = client.get("/dashboard")
    assert r.status_code == 302 and r.headers["Location"].endswith("/profile")
    r = client.post("/profile/password", data={"current_password": "Admin@12345", "new_password": "NewPass123",
                                               "confirm_password": "NewPass123"})
    assert r.status_code == 302
    assert client.get("/dashboard").status_code == 200


@pytest.mark.parametrize("weak", ["short1A", "alllowercase1", "NOLOWER123", "NoDigitsHere"])
def test_weak_passwords_rejected(auth_client, weak):
    r = auth_client.post("/profile/password", data={"current_password": "Admin@12345", "new_password": weak, "confirm_password": weak},
                         follow_redirects=True)
    assert b"Password" in r.data and b"changed successfully" not in r.data


def test_account_locks_after_repeated_failures(client):
    for _ in range(5):
        login(client, password="bad")
    r = login(client, password="Admin@12345")                  # even the correct password is refused while locked
    assert r.status_code == 429


def test_open_redirect_is_blocked(client, db):
    db.execute("UPDATE administrators SET must_change_password=0"); db.commit()
    r = client.post("/login?next=//evil.example.com", data={"username": "admin", "password": "Admin@12345"})
    assert r.status_code == 302 and "evil.example.com" not in r.headers["Location"]


def test_security_headers_and_cookie_flags(client):
    r = client.get("/login")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert "camera=(self)" in r.headers["Permissions-Policy"]
    cookie = login(client).headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_csrf_blocks_post_without_token(csrf_app):
    c = csrf_app.test_client()
    assert c.post("/login", data={"username": "admin", "password": "x"}).status_code == 400
    page = c.get("/login").get_data(as_text=True)
    token = extract_csrf(page)
    r = c.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": token})
    assert r.status_code == 401                               # token accepted, credentials rejected


def test_csrf_blocks_api_without_header(csrf_app):
    c = csrf_app.test_client()
    token = extract_csrf(c.get("/login").get_data(as_text=True))
    c.post("/login", data={"username": "admin", "password": "Admin@12345", "csrf_token": token})
    assert c.post("/api/recognize", json={"image": "x"}).status_code == 400
    assert c.post("/api/recognize", json={"image": "x"}, headers={"X-CSRF-Token": token}).status_code == 400  # token ok, image invalid

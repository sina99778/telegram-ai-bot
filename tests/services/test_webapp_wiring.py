from app.core.config import settings
from app.bot.keyboards.reply import get_main_menu
from app.webapp.routes import webapp_router


def test_webapp_routes_registered():
    paths = {getattr(r, "path", None) for r in webapp_router.routes}
    assert "/webapp" in paths
    assert "/webapp/api/me" in paths
    assert "/webapp/api/chat" in paths


def test_open_app_button_hidden_without_url(monkeypatch):
    monkeypatch.setattr(settings, "WEBAPP_URL", "")
    monkeypatch.setattr(settings, "WEBHOOK_URL", "")
    texts = [b.text for row in get_main_menu("en").keyboard for b in row]
    assert not any("Open App" in t for t in texts)


def test_open_app_button_shown_with_https_url(monkeypatch):
    monkeypatch.setattr(settings, "WEBAPP_URL", "https://bot.example.com/webapp")
    buttons = [b for row in get_main_menu("en").keyboard for b in row]
    app_buttons = [b for b in buttons if b.web_app is not None]
    assert len(app_buttons) == 1
    assert app_buttons[0].web_app.url == "https://bot.example.com/webapp"


def test_webapp_url_derived_from_webhook(monkeypatch):
    monkeypatch.setattr(settings, "WEBAPP_URL", "")
    monkeypatch.setattr(settings, "WEBHOOK_URL", "https://my.host/webhook")
    assert settings.webapp_url == "https://my.host/webapp"

"""Alpha fake-provider ASGI application."""

from app.providers.fake_app import FakeProviderSettings, create_fake_provider_app

app = create_fake_provider_app(FakeProviderSettings(provider_name="alpha"))

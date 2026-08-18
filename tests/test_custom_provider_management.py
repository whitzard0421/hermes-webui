"""Regression coverage for WebUI-managed named custom providers."""

import socket

import yaml

import api.config as config
import api.providers as providers


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


def _prepare(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "_get_config_path", lambda: config_path)
    monkeypatch.setattr(providers, "_get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(providers, "reload_config", lambda: None)
    monkeypatch.setattr(providers, "invalidate_models_cache", lambda: None)
    monkeypatch.setattr(providers, "invalidate_providers_cache", lambda: None)
    monkeypatch.setattr(providers.socket, "getaddrinfo", _public_dns)
    return config_path


def test_create_custom_provider_keeps_key_out_of_yaml(monkeypatch, tmp_path):
    config_path = _prepare(monkeypatch, tmp_path)

    result = providers.save_custom_provider({
        "name": "Example API",
        "base_url": "https://api.example.test/v1/",
        "api_mode": "codex_responses",
        "model": "example-model",
        "api_key": "sk-example-key-12345678",
        "discover_models": True,
    })

    assert result == {
        "ok": True,
        "provider": "custom:example-api",
        "action": "created",
    }
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    entry = saved["custom_providers"][0]
    assert entry["base_url"] == "https://api.example.test/v1"
    assert entry["key_env"] == "HERMES_WEBUI_CUSTOM_EXAMPLE_API_API_KEY"
    assert "api_key" not in entry
    assert "sk-example-key-12345678" not in config_path.read_text(encoding="utf-8")
    assert (
        "HERMES_WEBUI_CUSTOM_EXAMPLE_API_API_KEY=sk-example-key-12345678"
        in (tmp_path / ".env").read_text(encoding="utf-8")
    )


def test_rejects_private_custom_provider_address(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )

    result = providers.save_custom_provider({
        "name": "Local API",
        "base_url": "http://127.0.0.1:8080/v1",
        "api_mode": "openai_compatible",
        "model": "local-model",
    })

    assert result["ok"] is False
    assert "public address" in result["error"]


def test_cannot_delete_active_custom_provider(monkeypatch, tmp_path):
    config_path = _prepare(monkeypatch, tmp_path)
    config_path.write_text(yaml.safe_dump({
        "model": {"provider": "custom:example-api"},
        "custom_providers": [{
            "name": "Example API",
            "base_url": "https://api.example.test/v1",
            "model": "x",
        }],
    }), encoding="utf-8")

    result = providers.delete_custom_provider("custom:example-api")

    assert result["ok"] is False
    assert "active default" in result["error"]
    assert len(
        yaml.safe_load(config_path.read_text(encoding="utf-8"))["custom_providers"]
    ) == 1


def test_existing_named_provider_map_is_listed_as_custom(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(providers, "_PROVIDER_DISPLAY", {})
    monkeypatch.setattr(providers, "_PROVIDER_MODELS", {})
    monkeypatch.setattr(providers, "_OAUTH_PROVIDERS", frozenset())
    monkeypatch.setattr(providers, "plugin_model_provider_ids", lambda: set())
    monkeypatch.setattr(providers, "get_config", lambda: {
        "model": {"provider": "custom:whitzard-api"},
        "providers": {"whitzard-api": {
            "api": "https://api.example.test/v1",
            "transport": "codex_responses",
            "default_model": "example-model",
            "key_env": "EXAMPLE_API_KEY",
        }},
    })
    providers.invalidate_providers_cache()

    listed = providers.get_providers()["providers"]

    assert len(listed) == 1
    entry = listed[0]
    assert entry["id"] == "custom:whitzard-api"
    assert entry["config_source"] == "providers"
    assert entry["base_url"] == "https://api.example.test/v1"
    assert entry["api_mode"] == "codex_responses"
    assert entry["default_model"] == "example-model"


def test_edit_existing_named_provider_map_preserves_schema(monkeypatch, tmp_path):
    config_path = _prepare(monkeypatch, tmp_path)
    config_path.write_text(yaml.safe_dump({"providers": {"whitzard-api": {
        "api": "https://api.example.test/v1",
        "transport": "codex_responses",
        "default_model": "old-model",
        "key_env": "EXAMPLE_API_KEY",
    }}}), encoding="utf-8")

    result = providers.save_custom_provider({
        "provider": "custom:whitzard-api",
        "config_source": "providers",
        "name": "whitzard-api",
        "base_url": "https://new.example.test/v1",
        "api_mode": "chat_completions",
        "model": "new-model",
    })

    assert result["ok"] is True
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))["providers"][
        "whitzard-api"
    ]
    assert saved["api"] == "https://new.example.test/v1"
    assert saved["transport"] == "chat_completions"
    assert saved["default_model"] == "new-model"
    assert "base_url" not in saved and "api_mode" not in saved


def test_custom_provider_probe_returns_bounded_model_list(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    import api.onboarding as onboarding

    seen = {}

    def fake_probe(provider, base_url, api_key):
        seen.update(provider=provider, base_url=base_url, api_key=api_key)
        return {
            "ok": True,
            "models": [{"id": "one"}, {"id": "one"}, {"id": "two"}],
        }

    monkeypatch.setattr(onboarding, "probe_provider_endpoint", fake_probe)
    result = providers.probe_custom_provider_models({
        "name": "Example",
        "base_url": "https://api.example.test/v1",
        "api_mode": "codex_responses",
        "api_key": "sk-example-key-12345678",
    })

    assert result == {
        "ok": True,
        "models": [{"id": "one", "label": "one"}, {"id": "two", "label": "two"}],
    }
    assert seen["provider"] == "custom"
    assert seen["base_url"] == "https://api.example.test/v1"

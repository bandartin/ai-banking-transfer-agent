from src.awx_runtime.credentials import extract_secret_value, resolve_openai_credential
from src.awx_runtime.redaction import redact_mapping, redact_text


def test_extract_secret_value_prefers_named_variable():
    payload = [
        {
            "credentialId": "cred-1",
            "variables": [
                {"attributeName": "BASE_URL", "attributeValue": "https://example.test"},
                {"attributeName": "OPENAI_API_KEY", "attributeValue": "sk-awx-secret"},
            ],
        }
    ]

    assert extract_secret_value(payload) == "sk-awx-secret"


def test_resolve_openai_credential_uses_local_fallback_without_awx_service():
    resolved = resolve_openai_credential(
        {
            "OPENAI_API_KEY": "sk-local-secret",
            "AWX_CREDENTIAL_SERVICE_ID": "",
            "AWX_CREDENTIAL_PROVIDER_ALIAS": "OpenAI",
            "AWX_CREDENTIAL_SERVICE_TYPE_NAME": "LLM",
        }
    )

    assert resolved is not None
    assert resolved.api_key == "sk-local-secret"
    assert resolved.source == "env"


def test_redact_text_masks_common_secret_shapes():
    text = (
        "OPENAI_API_KEY=sk-abcdefghijklmnop "
        "Authorization: Bearer abcdefghijklmnop "
        "account 024-01-0123456 phone 010-1234-5678"
    )

    redacted = redact_text(text)

    assert "sk-abcdefghijklmnop" not in redacted
    assert "Bearer abcdefghijklmnop" not in redacted
    assert "024-01-0123456" not in redacted
    assert "010-1234-5678" not in redacted
    assert "OPENAI_API_KEY=***" in redacted
    assert "****-3456" in redacted
    assert "010-****-5678" in redacted


def test_redact_mapping_masks_secret_keys_recursively():
    payload = {
        "api_key": "sk-abcdefghijklmnop",
        "nested": {"account": "024-01-0123456"},
        "items": [{"token": "plain-token"}, "call 01012345678"],
    }

    redacted = redact_mapping(payload)

    assert redacted["api_key"] == "***"
    assert redacted["nested"]["account"] == "****-3456"
    assert redacted["items"][0]["token"] == "***"
    assert redacted["items"][1] == "call 010-****-5678"

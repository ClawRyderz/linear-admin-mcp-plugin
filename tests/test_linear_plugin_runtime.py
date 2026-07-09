from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_RUNTIME_PATH = REPO_ROOT / "scripts" / "linear_plugin_runtime.py"
PROVIDER_REFS_PATH = REPO_ROOT / "config" / "provider_refs.json"
SPEC = spec_from_file_location("linear_admin_plugin_runtime", PLUGIN_RUNTIME_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load linear_plugin_runtime.py")
MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_committed_provider_config_contains_no_private_references() -> None:
    payload = json.loads(PROVIDER_REFS_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert "op://" not in serialized
    assert "op_service_account_token_file" not in payload
    assert payload["credential_sources"]["client_id_ref_candidates"] == []
    assert payload["credential_sources"]["client_secret_ref_candidates"] == []


def test_load_plugin_config_reads_json_object(tmp_path: Path) -> None:
    config_path = tmp_path / "provider_refs.json"
    config_path.write_text(
        json.dumps(
            {
                "credential_sources": {
                    "client_id_env_vars": ["LINEAR_CLIENT_ID"],
                    "client_secret_env_vars": ["LINEAR_CLIENT_SECRET"],
                }
            }
        ),
        encoding="utf-8",
    )

    payload = MODULE.load_plugin_config(config_path)

    assert payload["credential_sources"]["client_id_env_vars"] == ["LINEAR_CLIENT_ID"]


def test_resolve_linear_client_credentials_uses_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "provider_refs.json"
    config_path.write_text(
        json.dumps(
            {
                "credential_sources": {
                    "client_id_env_vars": ["LINEAR_CLIENT_ID"],
                    "client_secret_env_vars": ["LINEAR_CLIENT_SECRET"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LINEAR_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("LINEAR_CLIENT_SECRET", "env-client-secret")

    credentials = MODULE.resolve_linear_client_credentials(config_path)

    assert credentials.client_id == "env-client-id"
    assert credentials.client_secret == "env-client-secret"


def test_filter_schema_find_payload_returns_matching_types_and_root_fields() -> None:
    payload = {
        "data": {
            "__schema": {
                "types": [
                    {"name": "Template", "kind": "OBJECT"},
                    {"name": "CustomView", "kind": "OBJECT"},
                    {"name": "User", "kind": "OBJECT"},
                ]
            },
            "mutationType": {
                "fields": [
                    {"name": "templateCreate"},
                    {"name": "customViewDelete"},
                    {"name": "issueCreate"},
                ]
            },
            "queryType": {
                "fields": [
                    {"name": "templates"},
                    {"name": "customViews"},
                    {"name": "viewer"},
                ]
            },
        }
    }

    result = MODULE.filter_schema_find_payload(payload=payload, needles=["template", "view"])

    assert result["mutation_fields"] == ["customViewDelete", "templateCreate"]
    assert result["query_fields"] == ["customViews", "templates"]
    assert result["types"] == [
        {"kind": "OBJECT", "name": "CustomView"},
        {"kind": "OBJECT", "name": "Template"},
    ]


def test_main_mint_token_metadata_only_issues_one_token_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider_refs.json"
    config_path.write_text(
        json.dumps(
            {
                "credential_sources": {
                    "client_id_env_vars": ["LINEAR_CLIENT_ID"],
                    "client_secret_env_vars": ["LINEAR_CLIENT_SECRET"],
                },
                "scope": "read,write",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LINEAR_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("LINEAR_CLIENT_SECRET", "env-client-secret")
    issued_scopes: list[str] = []

    def fake_issue_token(*, credentials: object, scope: str, timeout_seconds: float = 30.0) -> object:
        issued_scopes.append(scope)
        return MODULE.LinearAccessToken(
            access_token="token",
            token_type="Bearer",
            expires_in=3600,
            scope=scope,
        )

    monkeypatch.setattr(MODULE, "issue_linear_client_credentials_token", fake_issue_token)

    exit_code = MODULE.main(
        [
            "--config-file",
            str(config_path),
            "mint-token-metadata",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert issued_scopes == ["read,write"]
    assert output["token_type"] == "Bearer"

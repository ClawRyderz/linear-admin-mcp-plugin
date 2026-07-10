#!/usr/bin/env python3

"""Portable Linear GraphQL runtime for the local Linear Admin MCP server."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LINEAR_OAUTH_TOKEN_URL = "https://api.linear.app/oauth/token"
LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
CONFIG_ENV_VARS = ("LINEAR_ADMIN_CONFIG_FILE", "LINEAR_ADMIN_PLUGIN_CONFIG_FILE")
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "provider_refs.json"
DEFAULT_SCOPE = "read,write"
OP_AUTH_ENV_KEYS = frozenset(
    {
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN_FILE",
    }
)

SCHEMA_FIND_QUERY = """
query SchemaFindProbe {
  __schema {
    types {
      name
      kind
    }
  }
  mutationType: __type(name: "Mutation") {
    fields {
      name
    }
  }
  queryType: __type(name: "Query") {
    fields {
      name
    }
  }
}
""".strip()

SCHEMA_TYPE_QUERY = """
query SchemaTypeProbe($name: String!) {
  __type(name: $name) {
    name
    kind
    fields {
      name
      args {
        name
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
            }
          }
        }
      }
      type {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
    inputFields {
      name
      type {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
    enumValues {
      name
    }
  }
}
""".strip()


@dataclass(frozen=True, slots=True)
class LinearClientCredentials:
    client_id: str
    client_secret: str

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("Linear client_id must be non-empty.")
        if not self.client_secret.strip():
            raise ValueError("Linear client_secret must be non-empty.")


@dataclass(frozen=True, slots=True)
class LinearAccessToken:
    access_token: str
    token_type: str
    expires_in: int
    scope: str

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise ValueError("Linear access token must be non-empty.")
        if self.token_type.strip().lower() != "bearer":
            raise ValueError("Linear token type must be Bearer.")
        if self.expires_in <= 0:
            raise ValueError("Linear access token expiry must be positive.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Portable Linear GraphQL runtime for local MCP use."
    )
    parser.add_argument(
        "--config-file",
        default=str(default_config_path()),
        help="Path to the Linear Admin provider refs JSON file.",
    )
    parser.add_argument(
        "--scope",
        help="Optional scope override for the Linear client_credentials request.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("mint-token-metadata")

    schema_find_parser = subparsers.add_parser("schema-find")
    schema_find_parser.add_argument(
        "--contains",
        action="append",
        required=True,
        help="Case-insensitive substring to search for. Repeat for multiple needles.",
    )

    schema_type_parser = subparsers.add_parser("schema-type")
    schema_type_parser.add_argument("--name", required=True, help="Type name to inspect.")

    graphql_parser = subparsers.add_parser("graphql")
    graphql_source = graphql_parser.add_mutually_exclusive_group(required=True)
    graphql_source.add_argument("--query")
    graphql_source.add_argument("--query-file")
    graphql_parser.add_argument("--variables", default="{}")

    args = parser.parse_args(argv)
    config_file = Path(args.config_file)

    if args.command == "mint-token-metadata":
        token = issue_linear_client_credentials_token(
            credentials=resolve_linear_client_credentials(config_file),
            scope=args.scope or load_plugin_config(config_file).get("scope", DEFAULT_SCOPE),
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(
                {
                    "token_type": token.token_type,
                    "expires_in": token.expires_in,
                    "scope": token.scope,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    access_token = resolve_linear_access_token(
        config_file=config_file,
        scope_override=args.scope,
        timeout_seconds=args.timeout_seconds,
    )

    if args.command == "schema-find":
        payload = graphql_request(
            access_token=access_token,
            query=SCHEMA_FIND_QUERY,
            variables={},
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(
                filter_schema_find_payload(payload=payload, needles=args.contains),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "schema-type":
        payload = graphql_request(
            access_token=access_token,
            query=SCHEMA_TYPE_QUERY,
            variables={"name": args.name},
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "graphql":
        query = args.query
        if query is None:
            query = Path(args.query_file).read_text(encoding="utf-8")
        try:
            variables = json.loads(args.variables)
        except json.JSONDecodeError as exc:
            raise ValueError("--variables must be valid JSON.") from exc
        if not isinstance(variables, dict):
            raise ValueError("--variables must decode to a JSON object.")
        payload = graphql_request(
            access_token=access_token,
            query=query,
            variables=variables,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"Unhandled command {args.command!r}.")


def default_config_path() -> Path:
    configured_path = next(
        (os.environ[name] for name in CONFIG_ENV_VARS if os.environ.get(name, "").strip()),
        str(DEFAULT_CONFIG_PATH),
    )
    return Path(configured_path).expanduser()


def load_plugin_config(config_file: Path | None = None) -> dict[str, Any]:
    resolved = (config_file or default_config_path()).expanduser()
    if not resolved.exists():
        raise ValueError(f"Linear Admin config file not found: {resolved}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Linear Admin config must contain a JSON object.")
    return payload


def resolve_linear_client_credentials(config_file: Path | None = None) -> LinearClientCredentials:
    config = load_plugin_config(config_file)
    credential_sources = config.get("credential_sources")
    if not isinstance(credential_sources, dict):
        raise ValueError("Linear Admin config must contain credential_sources.")
    service_account_token_file = resolve_service_account_token_file(config)
    client_id = resolve_candidate_secret(
        candidate_refs=normalize_string_list(
            credential_sources.get("client_id_ref_candidates"),
            field_name="client_id_ref_candidates",
        ),
        candidate_env_vars=normalize_string_list(
            credential_sources.get("client_id_env_vars"),
            field_name="client_id_env_vars",
        ),
        service_account_token_file=service_account_token_file,
        secret_label="client id",
    )
    client_secret = resolve_candidate_secret(
        candidate_refs=normalize_string_list(
            credential_sources.get("client_secret_ref_candidates"),
            field_name="client_secret_ref_candidates",
        ),
        candidate_env_vars=normalize_string_list(
            credential_sources.get("client_secret_env_vars"),
            field_name="client_secret_env_vars",
        ),
        service_account_token_file=service_account_token_file,
        secret_label="client secret",
    )
    return LinearClientCredentials(client_id=client_id, client_secret=client_secret)


def resolve_linear_access_token(
    *,
    config_file: Path | None = None,
    scope_override: str | None = None,
    timeout_seconds: float = 30.0,
) -> str:
    config = load_plugin_config(config_file)
    token = issue_linear_client_credentials_token(
        credentials=resolve_linear_client_credentials(config_file),
        scope=scope_override or str(config.get("scope", DEFAULT_SCOPE)),
        timeout_seconds=timeout_seconds,
    )
    return token.access_token


def normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array when present.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        stripped = item.strip()
        if stripped:
            normalized.append(stripped)
    return normalized


def resolve_service_account_token_file(config: dict[str, Any]) -> str | None:
    env_value = os.environ.get("LINEAR_ADMIN_OP_SERVICE_ACCOUNT_TOKEN_FILE", "").strip()
    if env_value:
        return env_value
    configured = config.get("op_service_account_token_file")
    if configured is None:
        return None
    if not isinstance(configured, str):
        raise ValueError("op_service_account_token_file must be a string when present.")
    stripped = configured.strip()
    return stripped or None


def resolve_candidate_secret(
    *,
    candidate_refs: list[str],
    candidate_env_vars: list[str],
    service_account_token_file: str | None,
    secret_label: str,
) -> str:
    for env_name in candidate_env_vars:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    for reference in candidate_refs:
        try:
            return read_secret_from_1password(
                reference,
                service_account_token_file=service_account_token_file,
            )
        except ValueError:
            continue
    raise ValueError(
        f"Unable to resolve the Linear {secret_label}. Update env vars or 1Password refs."
    )


def read_secret_from_1password(
    reference: str,
    *,
    service_account_token_file: str | None,
) -> str:
    if not reference.strip():
        raise ValueError("1Password reference must be non-empty.")
    env = {key: value for key, value in os.environ.items() if key not in OP_AUTH_ENV_KEYS}
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    token_file = service_account_token_file or os.environ.get("OP_SERVICE_ACCOUNT_TOKEN_FILE", "").strip()
    resolved_token_file = Path(token_file).expanduser() if token_file else None
    if not token and resolved_token_file is not None and resolved_token_file.exists():
        token = resolved_token_file.read_text(encoding="utf-8").strip()
    if token:
        env["OP_SERVICE_ACCOUNT_TOKEN"] = token
    completed = subprocess.run(
        ["op", "read", reference],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise ValueError(stderr or f"1Password read failed for {reference}.")
    secret_value = completed.stdout.strip()
    if not secret_value:
        raise ValueError(f"1Password read returned an empty value for {reference}.")
    return secret_value


def issue_linear_client_credentials_token(
    *,
    credentials: LinearClientCredentials,
    scope: str,
    timeout_seconds: float = 30.0,
) -> LinearAccessToken:
    normalized_scope = ",".join(piece.strip() for piece in scope.split(",") if piece.strip())
    if not normalized_scope:
        raise ValueError("Linear client_credentials scope must be non-empty.")
    basic_auth = base64.b64encode(
        f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        LINEAR_OAUTH_TOKEN_URL,
        data=urlencode(
            {
                "grant_type": "client_credentials",
                "scope": normalized_scope,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "linear-admin-mcp/1.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Linear client_credentials token mint failed with HTTP {exc.code}: {body or exc.reason}"
        ) from exc
    except URLError as exc:
        raise ValueError(f"Linear token mint failed: {exc.reason}") from exc

    return LinearAccessToken(
        access_token=str(payload.get("access_token", "")).strip(),
        token_type=str(payload.get("token_type", "")).strip(),
        expires_in=int(payload.get("expires_in", 0)),
        scope=str(payload.get("scope", "")).strip(),
    )


def graphql_request(
    *,
    access_token: str,
    query: str,
    variables: dict[str, object],
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    if not access_token.strip():
        raise ValueError("GraphQL requests require a non-empty access token.")
    if not query.strip():
        raise ValueError("GraphQL query must be non-empty.")
    request = Request(
        LINEAR_GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "linear-admin-mcp/1.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Linear GraphQL request failed with HTTP {exc.code}: {body or exc.reason}"
        ) from exc
    except URLError as exc:
        raise ValueError(f"Linear GraphQL request failed: {exc.reason}") from exc
    if "errors" in payload:
        raise ValueError(f"Linear GraphQL returned errors: {json.dumps(payload['errors'])}")
    if "data" not in payload:
        raise ValueError("Linear GraphQL response did not contain data.")
    return payload


def filter_schema_find_payload(
    *,
    payload: dict[str, object],
    needles: list[str],
) -> dict[str, object]:
    normalized_needles = tuple(needle.strip().lower() for needle in needles if needle.strip())
    if not normalized_needles:
        raise ValueError("At least one non-empty schema needle is required.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Schema probe payload must contain a data object.")

    def matches(name: str) -> bool:
        tokens = name_tokens(name)
        for needle in normalized_needles:
            plural_tokens = {needle, f"{needle}s", f"{needle}es"}
            if any(token in plural_tokens for token in tokens):
                return True
        return False

    type_matches = []
    for entry in coerce_list(data.get("__schema", {}), "types"):
        name = str(entry.get("name", "")).strip()
        kind = str(entry.get("kind", "")).strip()
        if name and matches(name):
            type_matches.append({"name": name, "kind": kind})

    mutation_matches = filter_root_field_matches(data.get("mutationType"), matches)
    query_matches = filter_root_field_matches(data.get("queryType"), matches)
    return {
        "needles": list(normalized_needles),
        "types": sorted(type_matches, key=lambda item: item["name"]),
        "mutation_fields": sorted(mutation_matches),
        "query_fields": sorted(query_matches),
    }


def coerce_list(container: object, key: str) -> list[dict[str, object]]:
    if not isinstance(container, dict):
        return []
    value = container.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def filter_root_field_matches(root: object, matcher: Any) -> list[str]:
    if not isinstance(root, dict):
        return []
    fields = root.get("fields")
    if not isinstance(fields, list):
        return []
    matches: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name", "")).strip()
        if name and matcher(name):
            matches.append(name)
    return matches


def name_tokens(name: str) -> tuple[str, ...]:
    if not name:
        return ()
    normalized = re.sub(r"[^0-9A-Za-z]+", " ", name)
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized)
    return tuple(piece.lower() for piece in spaced.split() if piece)


if __name__ == "__main__":
    raise SystemExit(main())

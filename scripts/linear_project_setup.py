#!/usr/bin/env python3

"""Sync shared Linear views and templates from a portable project config."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from linear_plugin_runtime import (  # noqa: E402
    default_config_path as default_provider_config_path,
    graphql_request,
    issue_linear_client_credentials_token,
    load_plugin_config,
    resolve_linear_client_credentials,
)


CUSTOM_VIEW_CREATE_MUTATION = """
mutation CreateCustomView($input: CustomViewCreateInput!) {
  customViewCreate(input: $input) {
    success
    customView {
      id
      name
    }
  }
}
""".strip()

CUSTOM_VIEW_UPDATE_MUTATION = """
mutation UpdateCustomView($id: String!, $input: CustomViewUpdateInput!) {
  customViewUpdate(id: $id, input: $input) {
    success
    customView {
      id
      name
    }
  }
}
""".strip()

TEMPLATE_CREATE_MUTATION = """
mutation CreateTemplate($input: TemplateCreateInput!) {
  templateCreate(input: $input) {
    success
    template {
      id
      name
      team {
        id
      }
    }
  }
}
""".strip()

TEMPLATE_UPDATE_MUTATION = """
mutation UpdateTemplate($id: String!, $input: TemplateUpdateInput!) {
  templateUpdate(id: $id, input: $input) {
    success
    template {
      id
      name
      team {
        id
      }
    }
  }
}
""".strip()


@dataclass(frozen=True, slots=True)
class CustomViewSpec:
    id: str
    name: str
    description: str
    team_id: str
    project_id: str
    filter_data: dict[str, object]
    shared: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Custom view id must be non-empty.")
        if not self.name.strip():
            raise ValueError("Custom view name must be non-empty.")
        if not self.description.strip():
            raise ValueError(f"Custom view {self.name!r} needs a description.")
        if not isinstance(self.filter_data, dict) or not self.filter_data:
            raise ValueError(f"Custom view {self.name!r} needs filterData.")


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    name: str
    description: str
    template_data: dict[str, object]
    type: str = "issue"
    team_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Template name must be non-empty.")
        if not self.description.strip():
            raise ValueError(f"Template {self.name!r} needs a description.")
        if not isinstance(self.template_data, dict) or not self.template_data:
            raise ValueError(f"Template {self.name!r} needs templateData.")


@dataclass(frozen=True, slots=True)
class ProjectSetupConfig:
    project_name: str
    project_id: str
    team_id: str
    custom_views: tuple[CustomViewSpec, ...]
    templates: tuple[TemplateSpec, ...]


@dataclass(frozen=True, slots=True)
class PlannedMutation:
    action: Literal["create", "update", "noop"]
    object_kind: Literal["custom_view", "template"]
    name: str
    payload: dict[str, object]
    existing_id: str | None = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upsert shared Linear views and templates from a project config."
    )
    parser.add_argument(
        "--project-config",
        required=True,
        help="Path to the project setup config JSON file.",
    )
    parser.add_argument(
        "--provider-config",
        default=str(default_provider_config_path()),
        help="Path to the provider refs JSON file.",
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
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the planned Linear mutations.",
    )
    args = parser.parse_args(argv)

    project_config = load_project_setup_config(Path(args.project_config))
    access_token = resolve_access_token(
        provider_config_path=Path(args.provider_config),
        scope_override=args.scope,
        timeout_seconds=args.timeout_seconds,
    )
    snapshot = fetch_setup_snapshot(
        access_token=access_token,
        project_config=project_config,
        timeout_seconds=args.timeout_seconds,
    )
    plan = plan_project_setup(snapshot, project_config)
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "summary": summarize_plan(plan),
                    "mutations": [serialize_planned_mutation(item) for item in plan],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    results = apply_plan(
        access_token=access_token,
        plan=plan,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "mode": "apply",
                "summary": summarize_plan(plan),
                "results": results,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def load_project_setup_config(path: Path) -> ProjectSetupConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Project setup config must contain a JSON object.")
    project_name = str(payload.get("project_name", "")).strip()
    project_id = str(payload.get("project_id", "")).strip()
    team_id = str(payload.get("team_id", "")).strip()
    if not project_name or not project_id or not team_id:
        raise ValueError("Project setup config requires project_name, project_id, and team_id.")
    custom_views_payload = payload.get("custom_views")
    if not isinstance(custom_views_payload, list) or not custom_views_payload:
        raise ValueError("Project setup config requires a non-empty custom_views array.")
    templates_payload = payload.get("templates")
    if not isinstance(templates_payload, list) or not templates_payload:
        raise ValueError("Project setup config requires a non-empty templates array.")

    custom_views: list[CustomViewSpec] = []
    for entry in custom_views_payload:
        if not isinstance(entry, dict):
            raise ValueError("Each custom view entry must be an object.")
        custom_views.append(
            CustomViewSpec(
                id=str(entry.get("id", "")).strip(),
                name=str(entry.get("name", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                team_id=team_id,
                project_id=project_id,
                filter_data=_require_dict(entry.get("filterData"), field_name="filterData"),
                shared=bool(entry.get("shared", True)),
            )
        )

    templates: list[TemplateSpec] = []
    for entry in templates_payload:
        if not isinstance(entry, dict):
            raise ValueError("Each template entry must be an object.")
        team_override = entry.get("teamId")
        if team_override is not None and not isinstance(team_override, str):
            raise ValueError("teamId must be a string when present on a template.")
        templates.append(
            TemplateSpec(
                name=str(entry.get("name", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                template_data=_require_dict(entry.get("templateData"), field_name="templateData"),
                type=str(entry.get("type", "issue")).strip() or "issue",
                team_id=(team_override.strip() if isinstance(team_override, str) and team_override.strip() else None),
            )
        )

    return ProjectSetupConfig(
        project_name=project_name,
        project_id=project_id,
        team_id=team_id,
        custom_views=tuple(custom_views),
        templates=tuple(templates),
    )


def _require_dict(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field_name} must be a non-empty object.")
    return value


def resolve_access_token(
    *,
    provider_config_path: Path,
    scope_override: str | None,
    timeout_seconds: float,
) -> str:
    provider_config = load_plugin_config(provider_config_path)
    token = issue_linear_client_credentials_token(
        credentials=resolve_linear_client_credentials(provider_config_path),
        scope=scope_override or str(provider_config.get("scope", "read,write")),
        timeout_seconds=timeout_seconds,
    )
    return token.access_token


def fetch_setup_snapshot(
    *,
    access_token: str,
    project_config: ProjectSetupConfig,
    timeout_seconds: float,
) -> dict[str, object]:
    payload = graphql_request(
        access_token=access_token,
        query=build_snapshot_query(project_config),
        variables={},
        timeout_seconds=timeout_seconds,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Project setup snapshot response was missing data.")
    return data


def build_snapshot_query(project_config: ProjectSetupConfig) -> str:
    custom_view_queries = []
    for index, view in enumerate(project_config.custom_views):
        custom_view_queries.append(
            f'  customView_{index}: customView(id: "{view.id}") {{ ...CustomViewFields }}'
        )
    joined_custom_views = "\n".join(custom_view_queries)
    return (
        "query ProjectSetupSnapshot {\n"
        f"{joined_custom_views}\n"
        "  templates {\n"
        "    id\n"
        "    name\n"
        "    type\n"
        "    description\n"
        "    team {\n"
        "      id\n"
        "    }\n"
        "    templateData\n"
        "  }\n"
        "}\n\n"
        "fragment CustomViewFields on CustomView {\n"
        "  id\n"
        "  name\n"
        "  description\n"
        "  shared\n"
        "  team {\n"
        "    id\n"
        "  }\n"
        "  filterData\n"
        "}\n"
    )


def plan_project_setup(
    snapshot: dict[str, object],
    project_config: ProjectSetupConfig,
) -> list[PlannedMutation]:
    template_index = index_existing_templates(snapshot)
    planned: list[PlannedMutation] = []

    for index, spec in enumerate(project_config.custom_views):
        payload = custom_view_input(spec)
        existing_value = snapshot.get(f"customView_{index}")
        existing = existing_value if isinstance(existing_value, dict) else None
        if existing is None:
            planned.append(
                PlannedMutation(
                    action="create",
                    object_kind="custom_view",
                    name=spec.name,
                    payload=payload,
                )
            )
            continue
        if custom_view_matches(existing, payload):
            planned.append(
                PlannedMutation(
                    action="noop",
                    object_kind="custom_view",
                    name=spec.name,
                    payload=payload,
                    existing_id=str(existing["id"]),
                )
            )
            continue
        planned.append(
            PlannedMutation(
                action="update",
                object_kind="custom_view",
                name=spec.name,
                payload=payload,
                existing_id=str(existing["id"]),
            )
        )

    for spec in project_config.templates:
        payload = template_input(spec)
        existing = template_index.get(spec.name)
        if existing is None:
            planned.append(
                PlannedMutation(
                    action="create",
                    object_kind="template",
                    name=spec.name,
                    payload=payload,
                )
            )
            continue
        if template_matches(existing, payload):
            planned.append(
                PlannedMutation(
                    action="noop",
                    object_kind="template",
                    name=spec.name,
                    payload=payload,
                    existing_id=str(existing["id"]),
                )
            )
            continue
        planned.append(
            PlannedMutation(
                action="update",
                object_kind="template",
                name=spec.name,
                payload=payload,
                existing_id=str(existing["id"]),
            )
        )
    return planned


def apply_plan(
    *,
    access_token: str,
    plan: list[PlannedMutation],
    timeout_seconds: float,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in plan:
        if item.action == "noop":
            results.append(
                {
                    "action": "noop",
                    "object_kind": item.object_kind,
                    "name": item.name,
                    "id": item.existing_id,
                }
            )
            continue
        if item.object_kind == "custom_view":
            results.append(
                apply_custom_view_mutation(
                    access_token=access_token,
                    mutation=item,
                    timeout_seconds=timeout_seconds,
                )
            )
        else:
            results.append(
                apply_template_mutation(
                    access_token=access_token,
                    mutation=item,
                    timeout_seconds=timeout_seconds,
                )
            )
    return results


def apply_custom_view_mutation(
    *,
    access_token: str,
    mutation: PlannedMutation,
    timeout_seconds: float,
) -> dict[str, object]:
    if mutation.action == "create":
        payload = graphql_request(
            access_token=access_token,
            query=CUSTOM_VIEW_CREATE_MUTATION,
            variables={"input": mutation.payload},
            timeout_seconds=timeout_seconds,
        )
        response = payload["data"]["customViewCreate"]
        created = response["customView"]
        return {
            "action": "create",
            "object_kind": "custom_view",
            "name": mutation.name,
            "id": created["id"],
            "success": response["success"],
        }
    if mutation.action == "update":
        payload = graphql_request(
            access_token=access_token,
            query=CUSTOM_VIEW_UPDATE_MUTATION,
            variables={"id": mutation.existing_id, "input": mutation.payload},
            timeout_seconds=timeout_seconds,
        )
        response = payload["data"]["customViewUpdate"]
        updated = response["customView"]
        return {
            "action": "update",
            "object_kind": "custom_view",
            "name": mutation.name,
            "id": updated["id"],
            "success": response["success"],
        }
    raise AssertionError(f"Unhandled custom view action {mutation.action!r}.")


def apply_template_mutation(
    *,
    access_token: str,
    mutation: PlannedMutation,
    timeout_seconds: float,
) -> dict[str, object]:
    if mutation.action == "create":
        payload = graphql_request(
            access_token=access_token,
            query=TEMPLATE_CREATE_MUTATION,
            variables={"input": mutation.payload},
            timeout_seconds=timeout_seconds,
        )
        response = payload["data"]["templateCreate"]
        created = response["template"]
        return {
            "action": "create",
            "object_kind": "template",
            "name": mutation.name,
            "id": created["id"],
            "scope": "workspace" if created.get("team") is None else "team",
            "success": response["success"],
        }
    if mutation.action == "update":
        payload = graphql_request(
            access_token=access_token,
            query=TEMPLATE_UPDATE_MUTATION,
            variables={"id": mutation.existing_id, "input": mutation.payload},
            timeout_seconds=timeout_seconds,
        )
        response = payload["data"]["templateUpdate"]
        updated = response["template"]
        return {
            "action": "update",
            "object_kind": "template",
            "name": mutation.name,
            "id": updated["id"],
            "scope": "workspace" if updated.get("team") is None else "team",
            "success": response["success"],
        }
    raise AssertionError(f"Unhandled template action {mutation.action!r}.")


def index_existing_templates(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    templates = snapshot.get("templates")
    if not isinstance(templates, list):
        return {}
    indexed: dict[str, dict[str, object]] = {}
    for template in templates:
        if not isinstance(template, dict):
            continue
        name = str(template.get("name", "")).strip()
        if not name:
            continue
        indexed[name] = template
    return indexed


def custom_view_input(spec: CustomViewSpec) -> dict[str, object]:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "teamId": spec.team_id,
        "projectId": spec.project_id,
        "filterData": spec.filter_data,
        "shared": spec.shared,
    }


def template_input(spec: TemplateSpec) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": spec.name,
        "description": spec.description,
        "type": spec.type,
        "templateData": spec.template_data,
    }
    if spec.team_id is not None:
        payload["teamId"] = spec.team_id
    return payload


def custom_view_matches(existing: dict[str, object], desired_input: dict[str, object]) -> bool:
    team = existing.get("team")
    existing_team_id = team.get("id") if isinstance(team, dict) else None
    return (
        str(existing.get("id", "")).strip() == str(desired_input["id"]).strip()
        and str(existing.get("name", "")).strip() == str(desired_input["name"]).strip()
        and str(existing.get("description", "")).strip() == str(desired_input["description"]).strip()
        and bool(existing.get("shared")) is bool(desired_input["shared"])
        and existing_team_id == desired_input["teamId"]
        and normalize_json_value(existing.get("filterData"))
        == normalize_json_value(desired_input["filterData"])
    )


def template_matches(existing: dict[str, object], desired_input: dict[str, object]) -> bool:
    existing_team = existing.get("team")
    existing_team_id = existing_team.get("id") if isinstance(existing_team, dict) else None
    desired_team_id = desired_input.get("teamId")
    return (
        str(existing.get("name", "")).strip() == str(desired_input["name"]).strip()
        and str(existing.get("description", "")).strip() == str(desired_input["description"]).strip()
        and str(existing.get("type", "")).strip() == str(desired_input["type"]).strip()
        and existing_team_id == desired_team_id
    )


def normalize_json_value(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return normalize_json_value(json.loads(stripped))
            except json.JSONDecodeError:
                return stripped
        return stripped
    if isinstance(value, dict):
        return {
            str(key): normalize_json_value(value[key])
            for key in sorted(value.keys(), key=str)
        }
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    return value


def summarize_plan(plan: list[PlannedMutation]) -> dict[str, int]:
    summary = {"create": 0, "update": 0, "noop": 0}
    for item in plan:
        summary[item.action] += 1
    return summary


def serialize_planned_mutation(mutation: PlannedMutation) -> dict[str, object]:
    return {
        "action": mutation.action,
        "existing_id": mutation.existing_id,
        "name": mutation.name,
        "object_kind": mutation.object_kind,
        "payload": mutation.payload,
    }


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SETUP_PATH = REPO_ROOT / "scripts" / "linear_project_setup.py"
MCP_SERVER_PATH = REPO_ROOT / "scripts" / "linear_admin_mcp.py"
RENDER_MCP_PATH = REPO_ROOT / "scripts" / "render_mcp_config.py"
INSTALL_PATH = REPO_ROOT / "scripts" / "install.py"
EXAMPLE_PROJECT_PATH = REPO_ROOT / "config" / "projects" / "example_project.json"

PROJECT_SPEC = spec_from_file_location("linear_admin_project_setup", PROJECT_SETUP_PATH)
if PROJECT_SPEC is None or PROJECT_SPEC.loader is None:
    raise RuntimeError("Unable to load linear_project_setup.py")
PROJECT_MODULE = module_from_spec(PROJECT_SPEC)
sys.modules[PROJECT_SPEC.name] = PROJECT_MODULE
PROJECT_SPEC.loader.exec_module(PROJECT_MODULE)

RENDER_SPEC = spec_from_file_location("linear_admin_render_mcp_config", RENDER_MCP_PATH)
if RENDER_SPEC is None or RENDER_SPEC.loader is None:
    raise RuntimeError("Unable to load render_mcp_config.py")
RENDER_MODULE = module_from_spec(RENDER_SPEC)
sys.modules[RENDER_SPEC.name] = RENDER_MODULE
RENDER_SPEC.loader.exec_module(RENDER_MODULE)

INSTALL_SPEC = spec_from_file_location("linear_admin_install", INSTALL_PATH)
if INSTALL_SPEC is None or INSTALL_SPEC.loader is None:
    raise RuntimeError("Unable to load install.py")
INSTALL_MODULE = module_from_spec(INSTALL_SPEC)
sys.modules[INSTALL_SPEC.name] = INSTALL_MODULE
INSTALL_SPEC.loader.exec_module(INSTALL_MODULE)

MCP_SPEC = spec_from_file_location("linear_admin_mcp_test", MCP_SERVER_PATH)
if MCP_SPEC is None or MCP_SPEC.loader is None:
    raise RuntimeError("Unable to load linear_admin_mcp.py")
MCP_MODULE = module_from_spec(MCP_SPEC)
sys.modules[MCP_SPEC.name] = MCP_MODULE
MCP_SPEC.loader.exec_module(MCP_MODULE)


def test_load_project_setup_config_reads_generic_example() -> None:
    config = PROJECT_MODULE.load_project_setup_config(EXAMPLE_PROJECT_PATH)

    assert config.project_name == "Example Project"
    assert len(config.custom_views) == 2
    assert len(config.templates) == 2
    assert config.custom_views[0].name == "Ready for Work"
    assert config.templates[0].name == "Implementation Task"


def test_committed_project_example_contains_no_private_workspace_details() -> None:
    serialized = EXAMPLE_PROJECT_PATH.read_text(encoding="utf-8")

    assert "YOUR_PROJECT_ID" in serialized
    assert "YOUR_TEAM_ID" in serialized
    assert "YOUR_READY_VIEW_ID" in serialized
    assert "YOUR_IN_PROGRESS_VIEW_ID" in serialized
    assert re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        serialized,
        re.IGNORECASE,
    ) is None


def test_project_setup_tools_require_an_explicit_config_file() -> None:
    setup_schemas = {
        schema["name"]: schema
        for schema in MCP_MODULE.TOOL_SCHEMAS
        if schema["name"] in {"linear_project_setup_plan", "linear_project_setup_apply"}
    }

    assert setup_schemas["linear_project_setup_plan"]["inputSchema"]["required"] == [
        "project_config_file"
    ]
    assert setup_schemas["linear_project_setup_apply"]["inputSchema"]["required"] == [
        "project_config_file"
    ]
    with pytest.raises(ValueError, match="project_config_file is required"):
        MCP_MODULE.resolve_project_config({})


def test_plan_project_setup_marks_matching_snapshot_entries_as_noop() -> None:
    config = PROJECT_MODULE.load_project_setup_config(EXAMPLE_PROJECT_PATH)
    snapshot = {
        "customView_0": {
            "id": config.custom_views[0].id,
            "name": config.custom_views[0].name,
            "description": config.custom_views[0].description,
            "shared": True,
            "team": {"id": config.team_id},
            "filterData": config.custom_views[0].filter_data,
        },
        "templates": [
            {
                "id": "template-1",
                "name": config.templates[0].name,
                "type": config.templates[0].type,
                "description": config.templates[0].description,
                "team": None,
                "templateData": config.templates[0].template_data,
            }
        ],
    }

    plan = PROJECT_MODULE.plan_project_setup(snapshot, config)
    noops = {(item.object_kind, item.name): item for item in plan if item.action == "noop"}

    assert ("custom_view", "Ready for Work") in noops
    assert ("template", "Implementation Task") in noops


def test_plan_project_setup_updates_existing_view_even_if_name_drifted() -> None:
    config = PROJECT_MODULE.load_project_setup_config(EXAMPLE_PROJECT_PATH)
    snapshot = {
        "customView_0": {
            "id": config.custom_views[0].id,
            "name": "Old Ready Queue",
            "description": config.custom_views[0].description,
            "shared": True,
            "team": {"id": config.team_id},
            "filterData": config.custom_views[0].filter_data,
        },
        "templates": [],
    }

    plan = PROJECT_MODULE.plan_project_setup(snapshot, config)
    ready_for_work = next(
        item for item in plan if item.object_kind == "custom_view" and item.name == "Ready for Work"
    )

    assert ready_for_work.action == "update"
    assert ready_for_work.existing_id == config.custom_views[0].id


def test_render_mcp_config_writes_absolute_paths(tmp_path: Path) -> None:
    bundle_root = tmp_path / "linear-admin"
    (bundle_root / "scripts").mkdir(parents=True)
    (bundle_root / "config").mkdir(parents=True)
    output_path = tmp_path / ".mcp.json"

    exit_code = RENDER_MODULE.main(
        [
            "--bundle-root",
            str(bundle_root),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    server = payload["mcpServers"]["linear-admin-local"]

    assert exit_code == 0
    assert server["args"] == [str(bundle_root / "scripts" / "linear_admin_mcp.py")]
    assert server["env"]["LINEAR_ADMIN_CONFIG_FILE"] == str(
        bundle_root / "config" / "provider_refs.json"
    )


def test_install_copies_bundle_and_renders_absolute_mcp(tmp_path: Path) -> None:
    destination = tmp_path / "linear-admin-installed"

    exit_code = INSTALL_MODULE.main(
        [
            "--bundle-root",
            str(REPO_ROOT),
            "--destination",
            str(destination),
        ]
    )

    payload = json.loads((destination / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["linear-admin-local"]

    assert exit_code == 0
    assert (destination / ".codex-plugin" / "plugin.json").exists()
    assert (destination / "scripts" / "linear_admin_mcp.py").exists()
    assert not (destination / ".git").exists()
    assert server["args"] == [str(destination / "scripts" / "linear_admin_mcp.py")]


def test_install_replaces_symlink_destination(tmp_path: Path) -> None:
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    destination = tmp_path / "linear-admin-link"
    destination.symlink_to(real_target, target_is_directory=True)

    exit_code = INSTALL_MODULE.main(
        [
            "--bundle-root",
            str(REPO_ROOT),
            "--destination",
            str(destination),
            "--force",
        ]
    )

    assert exit_code == 0
    assert destination.is_dir()
    assert not destination.is_symlink()
    assert (destination / ".codex-plugin" / "plugin.json").exists()

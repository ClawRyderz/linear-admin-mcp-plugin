---
name: linear-admin
description: Use the local Linear Admin MCP server for GraphQL schema inspection, shared custom views, workspace templates, project updates, or project setup sync from config.
---

# Linear Admin

## Overview

This bundle exposes a local-only Linear GraphQL admin path through MCP.

- It mints Linear app tokens from environment variables or user-configured 1Password references.
- It can inspect the live GraphQL schema.
- It can sync shared project views and workspace templates from a project config file.
- It can post project updates without browser automation.

## When to use it

Use these Linear Admin MCP tools when the user wants:

- shared custom views created or updated in Linear
- workspace or team template automation
- project status updates through the API
- GraphQL schema introspection for Linear capabilities
- reusable Linear setup across repos or friends

## Secret posture

- Never paste the Linear client secret, client id, bearer token, or 1Password service-account token into chat.
- Keep only the static OAuth app credentials in 1Password.
- Mint app access tokens at runtime and never persist them.
- Update `config/provider_refs.json` or a copied local equivalent rather than hardcoding credentials in repository files.

## Project presets

- Project setup configs live under `config/projects/`.
- `example_project.json` is a placeholder-only preset for shared views and workspace templates.
- Copy it to an untracked local file, replace every `YOUR_...` placeholder, and edit the filters and templates.
- Always run `linear_project_setup_plan` before `linear_project_setup_apply`.

## Tool routing

- Use `linear_schema_find` when you need to know whether the Linear API exposes a concept.
- Use `linear_schema_type` when you need the field shape for a specific GraphQL type.
- Use `linear_graphql_query` for one-off admin GraphQL operations.
- Use `linear_project_setup_plan` to preview project setup mutations from a config file.
- Use `linear_project_setup_apply` to apply the planned views and templates from a config file.

## Installation note

- The committed `.mcp.json` is a portable source-tree default for clients that load project MCP config.
- For an isolated local install, run `python3 scripts/install.py --destination ~/.local/share/linear-admin-mcp-plugin`.
- Codex and Claude Code manifests are included as optional harness adapters.

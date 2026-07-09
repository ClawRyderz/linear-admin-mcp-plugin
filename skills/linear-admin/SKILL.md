---
name: linear-admin
description: Use the local Linear Admin plugin when the user wants admin-grade Linear automation beyond the default connector, such as GraphQL schema inspection, shared custom views, workspace templates, project updates, or project setup sync from config.
---

# Linear Admin

## Overview

This plugin exposes a local-only Linear GraphQL admin path for Codex.

- It mints Linear app tokens from environment variables or user-configured 1Password references.
- It can inspect the live GraphQL schema.
- It can sync shared project views and workspace templates from a project config file.
- It can post project updates without browser automation.

## When to use it

Use this plugin first when the user wants:

- shared custom views created or updated in Linear
- workspace or team template automation
- project status updates through the API
- GraphQL schema introspection for Linear capabilities
- reusable Linear setup across repos or friends

## Secret posture

- Never paste the Linear client secret, client id, bearer token, or 1Password service-account token into chat.
- Keep only the static OAuth app credentials in 1Password.
- Mint short-lived access tokens at runtime.
- Update `config/provider_refs.json` or a copied local equivalent rather than hardcoding credentials in plugin files.

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

## Install note

- The committed `.mcp.json` is a portable source-tree default.
- For normal local use, run `python3 scripts/install_local_plugin.py --destination ~/.agents/plugins/plugins/linear-admin`.
- The installer copies the plugin and rewrites `.mcp.json` there with absolute local paths for Codex.

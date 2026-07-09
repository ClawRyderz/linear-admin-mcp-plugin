# Codex Linear Admin Plugin

A local Codex plugin for advanced Linear administration through the GraphQL API.

It adds schema inspection, raw GraphQL queries, shared custom-view management, workspace templates, and project setup sync. Write operations are explicit: preview a setup plan first, then apply it deliberately.

## What it provides

| Tool | Use it for |
| --- | --- |
| `linear_schema_find` | Find matching types, queries, and mutations in Linear's live GraphQL schema. |
| `linear_schema_type` | Inspect the fields and arguments for one GraphQL type. |
| `linear_graphql_query` | Run a one-off GraphQL query or mutation. |
| `linear_project_setup_plan` | Preview custom-view and template changes from a project config. |
| `linear_project_setup_apply` | Apply the previewed custom-view and template changes. |

This plugin is intentionally more powerful than the standard Linear connector. Treat raw GraphQL and apply operations as workspace-changing admin actions.

## Requirements

- Codex with plugin support
- Python 3.10 or newer
- A Linear OAuth2 app with **client credentials tokens enabled**
- The minimum Linear scopes needed for your workflow; the supplied config defaults to `read,write`
- Optional: the [1Password CLI](https://developer.1password.com/docs/cli/) for local Secret Reference resolution

Linear documents the [client credentials flow](https://linear.app/developers/oauth-2-0-authentication#client-credentials-tokens), available scopes, and the [`https://api.linear.app/graphql`](https://linear.app/developers/graphql) endpoint. See the official [Codex plugin guide](https://learn.chatgpt.com/docs/plugins) for current installation behavior.

## Install

Clone the repository, then copy the plugin into a personal marketplace directory:

```bash
git clone https://github.com/ClawRyderz/codex-linear-admin-plugin.git
cd codex-linear-admin-plugin
python3 scripts/install_local_plugin.py \
  --destination ~/.agents/plugins/plugins/linear-admin
```

The installer copies the bundle and renders absolute paths in the installed `.mcp.json`. Re-run it with `--force` to replace an existing install.

Add this entry to `~/.agents/plugins/marketplace.json`. If the file already contains other plugins, append only the `linear-admin` object to its existing `plugins` array.

```json
{
  "name": "personal",
  "interface": {
    "displayName": "Personal"
  },
  "plugins": [
    {
      "name": "linear-admin",
      "source": {
        "source": "local",
        "path": "./plugins/linear-admin"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

Restart the ChatGPT desktop app, open **Plugins**, choose **Personal**, and install **Linear Admin**. Start a new task after installation so the bundled skill and MCP tools are loaded.

## Configure authentication

No credentials or private 1Password references are included in this repository. The plugin requests a Linear client-credentials token at runtime and does not persist the resulting bearer token.

### Option 1: environment variables

Provide the OAuth app credentials through:

- `LINEAR_CLIENT_ID`
- `LINEAR_CLIENT_SECRET`

Set them in the trusted environment that launches Codex. Do not commit them to a shell profile, project file, or MCP manifest.

### Option 2: 1Password Secret References

Edit the installed file at `~/.agents/plugins/plugins/linear-admin/config/provider_refs.json`:

```json
{
  "credential_sources": {
    "client_id_ref_candidates": [
      "op://YOUR_VAULT/YOUR_LINEAR_OAUTH_ITEM/client_id"
    ],
    "client_secret_ref_candidates": [
      "op://YOUR_VAULT/YOUR_LINEAR_OAUTH_ITEM/client_secret"
    ],
    "client_id_env_vars": [
      "LINEAR_CLIENT_ID"
    ],
    "client_secret_env_vars": [
      "LINEAR_CLIENT_SECRET"
    ]
  },
  "scope": "read,write"
}
```

Authenticate the 1Password CLI normally, or use `OP_SERVICE_ACCOUNT_TOKEN`. If you keep that token in a protected local file, point to it with `OP_SERVICE_ACCOUNT_TOKEN_FILE` or `LINEAR_ADMIN_OP_SERVICE_ACCOUNT_TOKEN_FILE`.

## Configure a project

The committed project file contains placeholders only. Keep real workspace, team, project, view, and template details in an untracked file outside the installed plugin so a future `--force` install cannot overwrite them.

```bash
mkdir -p ~/.config/linear-admin/projects
cp config/projects/example_project.json \
  ~/.config/linear-admin/projects/my-project.json
```

Before using the file:

1. Replace every `YOUR_...` value.
2. Replace the example workflow states if your team uses different names.
3. For an existing custom view, use its real view ID.
4. For a new view, apply once and then save the returned Linear view ID into your local config so later runs update instead of duplicate it.

Project setup tools require an explicit `project_config_file`; there is no default project target.

## Use safely

Start with read-only inspection:

- “Use Linear Admin to find GraphQL schema fields related to templates.”
- “Inspect the `CustomViewCreateInput` type.”

For project setup, always plan before applying:

1. Call `linear_project_setup_plan` with the absolute path to your local project config.
2. Review every proposed `create`, `update`, and `noop` operation.
3. Call `linear_project_setup_apply` with the same file only when the plan is correct.

The command-line helper follows the same pattern. Omitting `--apply` is plan-only:

```bash
python3 scripts/linear_project_setup.py \
  --project-config ~/.config/linear-admin/projects/my-project.json \
  --provider-config config/provider_refs.json
```

Add `--apply` only after reviewing the plan.

## Security and privacy

- The MCP server runs locally over standard input/output.
- OAuth app credentials stay in environment variables or are resolved locally from 1Password.
- Bearer tokens are requested at runtime and are not written to disk by the plugin.
- Project configs can reveal private workspace structure even without credentials; do not commit real IDs, filters, names, or templates.
- Requests are sent directly to Linear's OAuth and GraphQL endpoints; Linear's terms and privacy policy apply.
- Raw GraphQL mutations and `linear_project_setup_apply` can modify shared workspace data.

Use the least privilege scopes that support your workflow. Linear's OAuth documentation specifically warns against requesting the `admin` scope unless it is necessary.

## Development

Run the test suite from the repository root:

```bash
python3 -m pytest tests -q
```

Key files:

- `.codex-plugin/plugin.json` — plugin manifest
- `.mcp.json` — portable source-tree MCP configuration
- `config/provider_refs.json` — empty, safe-to-publish credential-source template
- `config/projects/example_project.json` — placeholder-only project config
- `scripts/linear_admin_mcp.py` — local MCP server
- `scripts/linear_plugin_runtime.py` — OAuth and GraphQL runtime
- `scripts/linear_project_setup.py` — plan/apply project setup helper
- `skills/linear-admin/SKILL.md` — Codex routing and safety guidance

## License

[MIT](LICENSE)

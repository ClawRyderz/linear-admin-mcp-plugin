# Linear Admin MCP

A portable MCP server for advanced Linear administration through the GraphQL API.

The core server is harness-neutral. It speaks standard newline-delimited stdio MCP and can run in Claude Code, Codex, or any MCP client that can launch a local command. Native Claude Code and Codex plugin manifests are included as optional adapters.

## Tools

| Tool | Purpose | MCP safety hint |
| --- | --- | --- |
| `linear_schema_find` | Find matching types, queries, and mutations in Linear's live schema. | Read-only |
| `linear_schema_type` | Inspect one GraphQL type. | Read-only |
| `linear_graphql_query` | Run an arbitrary GraphQL query or mutation. | Potentially destructive |
| `linear_project_setup_plan` | Preview custom-view and template changes. | Read-only |
| `linear_project_setup_apply` | Apply custom-view and template changes. | Potentially destructive |

Write-capable tools are deliberately annotated conservatively so MCP clients can present appropriate approval UI.

## Compatibility

| Harness | Integration |
| --- | --- |
| Any stdio MCP client | Run `scripts/linear_admin_mcp.py` with Python. |
| Claude Code | Use `.claude-plugin/plugin.json`, `claude mcp add`, or the root `.mcp.json`. |
| Codex | Use `.codex-plugin/plugin.json`, `codex mcp add`, or the root `.mcp.json`. |

The server negotiates MCP protocol versions `2024-11-05`, `2025-03-26`, and `2025-06-18`. Standard JSONL framing is the default; legacy `Content-Length` framing remains supported for older clients.

## Requirements

- Python 3.10 or newer
- A Linear OAuth2 app with **client credentials tokens enabled**
- The minimum Linear scopes required for your workflow; the supplied config defaults to `read,write`
- Optional: the [1Password CLI](https://developer.1password.com/docs/cli/) for local Secret Reference resolution

Linear documents the [client credentials flow](https://linear.app/developers/oauth-2-0-authentication#client-credentials-tokens), available scopes, and the [`https://api.linear.app/graphql`](https://linear.app/developers/graphql) endpoint.

## Install

Clone the repository and create an isolated local bundle:

```bash
git clone https://github.com/ClawRyderz/linear-admin-mcp.git
cd linear-admin-mcp
python3 scripts/install.py \
  --destination ~/.local/share/linear-admin-mcp
```

The installer copies the bundle, excludes repository history and caches, and renders an absolute-path `.mcp.json`. Re-run it with `--force` to replace an existing installation.

## Configure authentication

No credentials or private 1Password references are included. Configure the installed copy at `~/.local/share/linear-admin-mcp/config/provider_refs.json`, use an external config through `LINEAR_ADMIN_CONFIG_FILE`, or provide credentials through environment variables.

### Environment variables

- `LINEAR_CLIENT_ID`
- `LINEAR_CLIENT_SECRET`

Set them only in the trusted environment that launches your MCP client. Do not commit them to a repository or MCP manifest.

### 1Password Secret References

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

Authenticate the 1Password CLI normally, or use `OP_SERVICE_ACCOUNT_TOKEN`. For a protected token file, set `OP_SERVICE_ACCOUNT_TOKEN_FILE` or `LINEAR_ADMIN_OP_SERVICE_ACCOUNT_TOKEN_FILE`.

## Configure a project

The committed project file contains placeholders only. Keep real workspace, project, view, and template details in an untracked file outside the installed bundle.

```bash
mkdir -p ~/.config/linear-admin-mcp/projects
cp ~/.local/share/linear-admin-mcp/config/projects/example_project.json \
  ~/.config/linear-admin-mcp/projects/my-project.json
```

Before using it:

1. Replace every `YOUR_...` value.
2. Replace the example workflow states if your team uses different names.
3. For an existing custom view, use its real view ID.
4. For a new view, apply once and save the returned Linear view ID so later runs update instead of duplicate it.

Project setup tools require an explicit `project_config_file`; there is no default mutation target.

## Connect a harness

### Claude Code

Load the native plugin for one session:

```bash
claude --plugin-dir ~/.local/share/linear-admin-mcp
```

This loads the bundled skill and MCP server. For a persistent user-level MCP registration without the skill:

```bash
claude mcp add linear-admin --scope user \
  -e LINEAR_ADMIN_CONFIG_FILE=$HOME/.local/share/linear-admin-mcp/config/provider_refs.json \
  -- python3 $HOME/.local/share/linear-admin-mcp/scripts/linear_admin_mcp.py
```

See [Claude Code's MCP documentation](https://code.claude.com/docs/en/mcp) for scopes and project `.mcp.json` approval behavior.

### Codex

Register the stdio server directly:

```bash
codex mcp add linear-admin \
  --env LINEAR_ADMIN_CONFIG_FILE=$HOME/.local/share/linear-admin-mcp/config/provider_refs.json \
  -- python3 $HOME/.local/share/linear-admin-mcp/scripts/linear_admin_mcp.py
```

The bundle also includes `.codex-plugin/plugin.json` and the `linear-admin` skill for Codex marketplace packaging. See the official [Codex plugin guide](https://learn.chatgpt.com/docs/plugins).

### Other MCP clients

Use the absolute-path `.mcp.json` produced by the installer, or adapt this entry to your client's config format:

```json
{
  "mcpServers": {
    "linear-admin": {
      "command": "python3",
      "args": [
        "/ABSOLUTE/PATH/linear-admin-mcp/scripts/linear_admin_mcp.py"
      ],
      "env": {
        "LINEAR_ADMIN_CONFIG_FILE": "/ABSOLUTE/PATH/linear-admin-mcp/config/provider_refs.json"
      }
    }
  }
}
```

## Use safely

Start with read-only inspection:

- “Find Linear schema fields related to templates.”
- “Inspect the `CustomViewCreateInput` type.”

For project setup:

1. Call `linear_project_setup_plan` with the absolute path to your local project config.
2. Review every proposed `create`, `update`, and `noop` operation.
3. Call `linear_project_setup_apply` with the same file only when the plan is correct.

The command-line helper follows the same pattern. Omitting `--apply` is plan-only:

```bash
python3 ~/.local/share/linear-admin-mcp/scripts/linear_project_setup.py \
  --project-config ~/.config/linear-admin-mcp/projects/my-project.json \
  --provider-config ~/.local/share/linear-admin-mcp/config/provider_refs.json
```

Add `--apply` only after reviewing the plan.

## Security and privacy

- The server runs locally over standard input/output.
- OAuth app credentials stay in environment variables or are resolved locally from 1Password.
- Bearer tokens are requested at runtime and are not written to disk by the server.
- Real project configs reveal private workspace structure; keep them outside version control.
- Requests go directly to Linear's OAuth and GraphQL endpoints.
- Raw GraphQL mutations and `linear_project_setup_apply` can modify shared workspace data.

Use the least privilege scopes that support your workflow. Linear warns against requesting the `admin` scope unless it is necessary.

## Development

```bash
python3 -m pytest tests -q
```

Key paths:

- `scripts/linear_admin_mcp.py` — harness-neutral MCP server
- `scripts/mcp_stdio.py` — standard JSONL stdio transport with legacy compatibility
- `.mcp.json` — portable source-tree MCP config
- `.claude-plugin/plugin.json` — Claude Code adapter
- `.codex-plugin/plugin.json` — Codex adapter
- `skills/linear-admin/SKILL.md` — cross-compatible agent skill
- `scripts/install.py` — generic local installer

## License

[MIT](LICENSE)

# Intuizi plugins for Claude

The official Claude plugin for [Intuizi](https://www.intuizi.com) and its Large Behavioral Model,
Intuizi's flagship large quantitative model (LQM), trained on de-identified, real-world behavioral
signals. Brands, agencies and publishers use it to build audiences from real-world behavior, size
them, and deliver them to their marketing destinations.

## Install

```
/plugin marketplace add intuizi/intuizi-claude-plugin
/plugin install intuizi@intuizi
```

Then run `/mcp`, choose **intuizi**, and approve access in your browser. Authentication is
OAuth 2.1 with PKCE, so no key is pasted anywhere.

## What it adds

- The Intuizi MCP server (`https://console.intuizi.com/api/v2/mcp`): 28 tools covering reference
  lookups, audience estimates and builds, lookalike models, cohorts, activations and usage, plus
  20 read-only reference documents the assistant can consult on its own.
- A skill that teaches the right order of operations and the points where you should be asked to
  confirm, because builds are metered and activations deliver real data.

Read-only tools are annotated read-only and delete tools are annotated destructive, so Claude
asks before anything that changes or removes data.

## Where it works

An MCP server bundled in a plugin loads in Claude Code, Cowork and cloud sessions. In claude.ai
chat, add the Intuizi connector instead; the plugin's skill still applies there.

## Requirements

An Intuizi console account. Intuizi serves customers under contract, so accounts are provisioned
at [console.intuizi.com](https://console.intuizi.com) rather than by self-serve sign-up. The
connector sees only the projects and data your own account can see, and datasets are enabled per
organization.

## Documentation

- Overview: <https://www.intuizi.com/mcp/>
- API and MCP reference (customers, after signing in): <https://console.intuizi.com/developers/>
- Support: <support@intuizi.com>

## License

MIT. See [LICENSE](LICENSE).

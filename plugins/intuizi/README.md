# Intuizi

Connects Claude to the Large Behavioral Model, [Intuizi](https://www.intuizi.com)'s flagship large
quantitative model (LQM), trained on de-identified, real-world behavioral signals. Brands, agencies
and publishers use it to build audiences from real-world behavior, size them, and deliver them to
their marketing destinations.

## What you get

28 tools wrapping the Intuizi API v2, plus 20 read-only reference documents the assistant can
consult on its own:

- **Reference lookups** for POI categories and brands, apps, web domains, CTV channels,
  Transactions merchants, demographic and profile attributes, countries and signal providers.
- **Audience estimates** that size an audience before you build it, creating nothing.
- **Audience builds** from POI visits, app usage, web domains, CTV viewing, Transactions,
  demographics, profile attributes, home location or your own cohorts, combined with AND, OR
  and NOT IN.
- **Lookalike models** to grow a completed audience.
- **Cohorts** from your own files or from an existing audience.
- **Activations** that deliver a completed audience to a destination configured in the
  Intuizi console, with a preview of exactly what a frequency range keeps.
- **Usage** against your organization's data-scan allowance.

Read-only tools are annotated read-only; delete and cancel tools are annotated destructive, so
Claude asks before running them.

## Requirements

An Intuizi console account. Intuizi is a platform for customers under contract, so accounts are
provisioned at [console.intuizi.com](https://console.intuizi.com) rather than by self-serve
sign-up. The connector sees only the projects and data your own account can see.

## Connecting

Install the plugin, then run `/mcp`, choose **intuizi**, and approve access in your browser.
Authentication is OAuth 2.1 with PKCE: no key is pasted anywhere, access tokens last about an
hour and refresh automatically, and changing your console password revokes every connector token.

## Documentation

- Public overview: https://www.intuizi.com/mcp/
- Full API and MCP reference (customers, after signing in): https://console.intuizi.com/developers/
- Support: support@intuizi.com

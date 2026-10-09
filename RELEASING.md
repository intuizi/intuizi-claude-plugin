# Releasing

This repository is the source for two directory listings of the Intuizi plugin:

- the Claude plugin, read from `plugins/intuizi/.claude-plugin/plugin.json`, and
- the ChatGPT plugin directory package, read from `plugins/intuizi/.codex-plugin/plugin.json`.

Both manifests sit in the same folder and share its assets, so check both listings when you change
a shared file.

## Versions

Both manifests carry the same version, and the build fails when they differ. A release raises
both. Each listing is uploaded or published only when its own content changed, so a listing can
skip a number. Tag each release commit with its version, for example `v1.0.2`.

## What changes where

The tools, their descriptions and input schemas, and the server instructions come from the live
MCP server at `https://console.intuizi.com/api/v2/mcp`, not from this repository.

In ChatGPT, a change to a tool's definition (its name, description, input schema, or annotations)
or to the server instructions goes live only after an OpenAI scan passes. OpenAI scans every day,
and **Rescan** under **MCPs** in the OpenAI dashboard requests a scan at once. When a scan holds an
update, the tool keeps its approved definition. A new tool stays unavailable until it is approved,
and a removed tool goes away after the next scan. What a tool does and returns changes as soon as
the server is deployed, so keep the server compatible with the approved tool schemas until the new
ones are live. If a deploy breaks the live contract, roll it back rather than wait for a scan.

The ChatGPT listing takes its text, links, starter prompts, and icon from this repository. The
Claude listing takes the plugin from here, but only its name, short description, and README are
sure to follow a new version. Check the other rows after you publish.

## ChatGPT plugin directory

The package is `.codex-plugin/plugin.json`, the icon it references, and the declaration of the
plugin's MCP server. OpenAI refuses an upload that drops the server ("Removing the MCP isn't
supported"), so the manifest sets `mcpServers` to `./.mcp.json`. The root `.mcp.json` in this folder
belongs to the Claude plugin and uses Claude's format, which OpenAI rejects, so the build packs
`.codex-plugin/mcp.json` as the ZIP's `.mcp.json`. That declaration must keep the server URL,
because the update flow cannot change it. The package declares no skills.
`scripts/testdata/openai-1.0.0-plugin.json` keeps OpenAI's export of 1.0.0, which had no MCP
declaration, and with classic zlib the build reproduces that ZIP from it byte for byte.

1. Edit `plugins/intuizi/.codex-plugin/plugin.json`. Keep `name`: OpenAI assigned it, and an update
   must keep it.
2. Raise `version` in both manifests, and replace `extensions.com.openai.publication.release_notes`
   with notes for this version. OpenAI needs release notes for every submission, and without them
   the previous version's notes carry over.
3. Open a pull request. CI tests the build script, builds the ZIP from the branch commit, and
   attaches it to the run. Merge once it passes.
4. On `main`, run `python3 scripts/build-openai-zip.py`. It checks the manifest against OpenAI's
   package rules, refuses files that differ from the commit, and writes
   `dist/app-6ab5004a37dc81918472cf526729e745-<version>.zip`, which holds the manifest, the icon,
   and the MCP declaration, nothing else. The sha256 it prints must match the build log of the CI
   run for that commit, which uses classic zlib. A Python linked to zlib-ng writes other bytes from
   the same files, so the build prints its zlib version.
5. In the OpenAI dashboard, open the plugin, choose **Upload plugin to make changes**, and upload
   that ZIP. If the upload check refuses it, no version is created: fix the package in a new pull
   request. Once the upload is accepted, tag the commit with the version, so the tag pins the
   exact ZIP. Check that **MCPs** still shows the connected server and its tools. If it does not, do
   not submit, and contact OpenAI support with the plugin ID,
   `plugin_asdk_app_6ab5004a37dc81918472cf526729e745`. Resolve the required setup and validation
   errors. Other findings, such as held tool updates, can go to the review team. Then submit the
   version for review. Only one review can be open at a time.
6. Publish the version once it is approved.
7. Check the public listing in light and dark mode: the icon, the links, and the starter prompts.

The ZIP attached to a CI run downloads from the run page wrapped in a second ZIP, which OpenAI
rejects. `gh run download <run-id> -n chatgpt-plugin-zip` unpacks it, or use the local build.

Review material stays out of this public repository. Reviewer credentials, test cases, and the demo
recording URL are entered in the dashboard, and a package that leaves them out keeps the saved
values. The build refuses a manifest that contains them, and it refuses every field it does not
check yet.

## Claude plugin directory

1. Change the files under `plugins/intuizi/` and raise `version` in both manifests. Installed copies
   use the version to detect an update. If you change the description, also change it in
   `.claude-plugin/marketplace.json` at the repository root, because that entry overrides
   `plugin.json` for people who installed from this marketplace.
2. Merge to `main`.
3. In the Claude directory dashboard, choose **Check for new commits**, then publish the row whose
   commit is the new commit on `main`. The **Publish update** button in the header can pick an older
   commit. Auto-publish is off.
4. After publishing, check the public listing, including the icon and the links. If a row did not
   update, ask Anthropic to refresh it. Never create a new submission for an existing plugin.

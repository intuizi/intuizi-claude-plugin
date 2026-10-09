"""Tests for build-openai-zip.py.

Run: python3 -m unittest discover -s scripts -p "test_*.py"

The tests build their own plugin folder in a temporary directory, so a release
that changes plugins/intuizi does not break them. One test checks that the live
package is valid.
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_openai_zip", HERE / "build-openai-zip.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

# testdata/openai-1.0.0-plugin.json is the manifest from OpenAI's release ZIP for
# version 1.0.0, byte for byte. Its only entry is that file.
EXPORT_MANIFEST = HERE / "testdata" / "openai-1.0.0-plugin.json"
EXPORT_MANIFEST_SHA256 = "240c91574bea909bb1857806b42b653e5f160b448f9def293d8fa560639b2b9e"
EXPORT_ZIP_SHA256 = "463ca1ffcfb19e6d59278d230b33a0c2bbad14f98c22518cfbeb34cb2579636a"


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width, height, pixels=None, interlace=0):
    """A small valid RGB PNG of the given size. pixels overrides the pixel size it holds."""
    data_width, data_height = pixels or (width, height)
    rows = b"".join(b"\x00" + b"\x00" * (data_width * 3) for _ in range(data_height))
    return (B.PNG_SIGNATURE
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, interlace))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


MCP_DECLARATION = json.dumps({"mcpServers": {"intuizi": {"url": B.MCP_URL}}}, indent=2) + "\n"

VALID = {
    "name": B.PUBLISHED_NAME,
    "version": "2.3.4",
    "description": "Connects ChatGPT to a test service.",
    "author": {"name": "Intuizi, Inc."},
    "mcpServers": "./.mcp.json",
    "interface": {
        "displayName": "Intuizi",
        "shortDescription": "Build and activate audiences",
        "longDescription": "First paragraph.\n\nSecond paragraph.",
        "developerName": "Intuizi, Inc.",
        "category": "Data & Analytics",
        "capabilities": [],
        "websiteURL": "https://www.example.com",
        "supportURL": "https://www.example.com/contact/",
        "privacyPolicyURL": "https://www.example.com/privacy/",
        "termsOfServiceURL": "https://www.example.com/terms/",
        "defaultPrompt": ["How big would my audience be?"],
        "logo": "./assets/icon.png",
        "composerIcon": "./assets/icon.png",
    },
    "extensions": {"com.openai": {"publication": {"release_notes": "First test release."}}},
}


class BuildOpenAIZipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "intuizi"
        # The Claude files sit beside the package, as they do in plugins/intuizi.
        for rel, text in {
            ".claude-plugin/plugin.json": json.dumps({"name": "intuizi", "version": VALID["version"]}),
            ".mcp.json": json.dumps({"intuizi": {"type": "http", "url": B.MCP_URL}}),
            B.MCP_SOURCE: MCP_DECLARATION,
            "README.md": "Claude plugin readme",
            "skills/demo/SKILL.md": "---\nname: demo\ndescription: A demo skill.\n---\nDo the demo.\n",
        }.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        self.write_asset("icon.png", png(64, 64))

    def write_asset(self, name, data):
        path = self.root / "assets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def check(self, change=None):
        manifest = copy.deepcopy(VALID)
        if change:
            change(manifest)
        return self.check_raw(json.dumps(manifest, indent=2).encode("utf-8"))

    def check_raw(self, data):
        path = self.root / B.MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        pkg = B.Package(self.root)
        B.validate(pkg)
        return pkg

    def assert_error(self, pkg, fragment):
        self.assertTrue(any(fragment in e for e in pkg.errors), f"no error containing {fragment!r}: {pkg.errors}")

    def ui(self, **fields):
        return lambda m: m["interface"].update(fields)

    # --- the package ---------------------------------------------------------

    def test_valid_package_packs_the_manifest_icon_and_mcp_declaration_only(self):
        pkg = self.check()
        self.assertEqual(pkg.errors, [])
        self.assertEqual(pkg.files, {B.MANIFEST: B.MANIFEST, "assets/icon.png": "assets/icon.png",
                                     ".mcp.json": B.MCP_SOURCE})

    def test_zip_carries_the_openai_mcp_declaration_not_claudes(self):
        target = B.build(self.check(), self.tmp / "out")
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read(".mcp.json").decode("utf-8"), MCP_DECLARATION)

    def test_mcp_declaration(self):
        source = self.root / B.MCP_SOURCE
        self.assert_error(self.check(lambda m: m.pop("mcpServers")), "drops the plugin's MCP server")
        self.assert_error(self.check(lambda m: m.update(mcpServers="./mcp.json")), "drops the plugin's MCP server")
        for config, fragment in (({"intuizi": {"url": B.MCP_URL}}, "exactly one server"),
                                 ({"mcpServers": {"a": {"url": B.MCP_URL}, "b": {"url": B.MCP_URL}}}, "exactly one"),
                                 ({"mcpServers": {"intuizi": {"type": "http", "url": B.MCP_URL}}}, "only a url"),
                                 ({"mcpServers": {"intuizi": {"url": "https://example.com/mcp"}}}, "must stay"),
                                 ({"mcpServers": {" ": {"url": B.MCP_URL}}}, "server name")):
            with self.subTest(config=config):
                source.write_text(json.dumps(config), encoding="utf-8")
                self.assert_error(self.check(), fragment)
        source.write_bytes(b"\xff")
        self.assert_error(self.check(), "UTF-8 JSON")
        source.unlink()
        self.assert_error(self.check(), "does not exist")

    def test_live_package_is_valid(self):
        pkg = B.Package(B.PLUGIN_ROOT)
        B.validate(pkg)
        self.assertEqual(pkg.errors, [])

    def test_build_is_reproducible(self):
        pkg = self.check()
        first = B.build(pkg, self.tmp / "a")
        second = B.build(pkg, self.tmp / "b")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), sorted(pkg.files))
            for info in archive.infolist():
                self.assertEqual((info.date_time, info.external_attr >> 16, info.create_system, info.compress_type),
                                 (B.ZIP_DATE, B.ZIP_MODE, 3, zipfile.ZIP_DEFLATED))

    def test_build_matches_openai_release_zip(self):
        data = EXPORT_MANIFEST.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), EXPORT_MANIFEST_SHA256,
                         "testdata changed, for example by a CRLF checkout")
        root = self.tmp / "export"
        (root / ".codex-plugin").mkdir(parents=True)
        (root / B.MANIFEST).write_bytes(data)
        pkg = B.Package(root)
        pkg.manifest = {"version": "1.0.0"}
        target = B.build(pkg, self.tmp / "out")
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.namelist(), [B.MANIFEST])
            self.assertEqual(archive.read(B.MANIFEST), data)
        if hasattr(zlib, "ZLIBNG_VERSION") or "ng" in zlib.ZLIB_RUNTIME_VERSION:
            self.skipTest("zlib-ng compresses differently from the zlib that built OpenAI's ZIP")
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), EXPORT_ZIP_SHA256)

    def test_failed_build_leaves_no_partial_zip(self):
        pkg = self.check()
        pkg.files["assets/missing.png"] = "assets/missing.png"
        out = self.tmp / "out"
        with self.assertRaises(FileNotFoundError):
            B.build(pkg, out)
        self.assertEqual(list(out.iterdir()), [])

    # --- rules ---------------------------------------------------------------

    def test_identity(self):
        self.assert_error(self.check(lambda m: m.update(name="intuizi")), "must stay")
        self.assert_error(self.check(lambda m: m.update(version="1.0")), "semantic version")
        self.assert_error(self.check(lambda m: m.update(version="2.3.4\n")), "semantic version")
        self.assert_error(self.check(lambda m: m.update(version="1.0.0-" + "x" * 64)), "semantic version")
        self.assert_error(self.check(lambda m: m.update(description="x" * 1025)), "the limit is 1024")
        self.assert_error(self.check(lambda m: m.pop("description")), "description is required")
        self.assert_error(self.check(lambda m: m["author"].pop("name")), "author.name is required")

    def test_both_listings_share_one_version(self):
        self.assert_error(self.check(lambda m: m.update(version="2.3.5")), "share one version")
        (self.root / B.CLAUDE_MANIFEST).write_text(json.dumps({"version": "2.3.5"}), encoding="utf-8")
        self.assertEqual(self.check(lambda m: m.update(version="2.3.5")).errors, [])

    def test_text(self):
        self.assert_error(self.check(self.ui(displayName="x" * 31)), "the limit is 30")
        self.assert_error(self.check(self.ui(shortDescription="Build\naudiences")), "one line")
        self.assert_error(self.check(self.ui(displayName="Intu\u200bizi")), "U+200B")
        self.assert_error(self.check(self.ui(developerName="Intuizi,\tInc.")), "U+0009")
        self.assert_error(self.check(self.ui(longDescription="One.\u2028Two.")), "U+2028")
        self.assert_error(self.check(self.ui(displayName="   ")), "non-empty")
        self.assertEqual(self.check(self.ui(longDescription="One.\n\nTwo.")).errors, [])

    def test_category(self):
        self.assert_error(self.check(self.ui(category="Marketing")), "category must be one of")

    def test_capabilities(self):
        self.assert_error(self.check(lambda m: m["interface"].pop("capabilities")), "use []")
        self.assert_error(self.check(self.ui(capabilities="Read")), "must be a list")
        self.assert_error(self.check(self.ui(capabilities=["Read\nWrite"])), "one line")
        self.assert_error(self.check(self.ui(capabilities=[" "])), "non-empty")
        self.assert_error(self.check(self.ui(capabilities=["Read"] * 21)), "the limit is 20")

    def test_links(self):
        self.assert_error(self.check(self.ui(supportURL="http://www.example.com/")), "https URL")
        self.assert_error(self.check(self.ui(websiteURL="https://user:pw@www.example.com")), "credentials")
        self.assert_error(self.check(self.ui(websiteURL="https://www.example.com/a b")), "a space")
        self.assert_error(self.check(self.ui(websiteURL="https://[")), "square bracket")
        self.assert_error(self.check(lambda m: m["interface"].pop("termsOfServiceURL")), "termsOfServiceURL is required")

    def test_prompts(self):
        self.assert_error(self.check(self.ui(defaultPrompt=["One", "Two", "Three", "Four"])), "the limit is 3")
        self.assert_error(self.check(self.ui(defaultPrompt=["x" * 129])), "the limit is 128")
        self.assert_error(self.check(self.ui(defaultPrompt=["Ask @Intuizi"])), "@mention")
        self.assert_error(self.check(self.ui(defaultPrompt=["Same  prompt", "Same prompt"])), "repeats")
        self.assert_error(self.check(self.ui(defaultPrompt=["Two\nlines"])), "one line")
        self.assertEqual(self.check(self.ui(defaultPrompt=["Email the report to ops@example.com"])).errors, [])

    def test_icons(self):
        self.assert_error(self.check(lambda m: m["interface"].pop("logo")), "logo is required")
        self.write_asset("wide.png", png(100, 50))
        self.write_asset("tiny.png", png(32, 32))
        self.write_asset("icon.jpg", png(64, 64))
        good = png(64, 64)
        self.write_asset("cut.png", good[:40])
        self.write_asset("crc.png", good[:-20] + bytes([good[-20] ^ 1]) + good[-19:])
        self.write_asset("liar.png", png(512, 512, pixels=(64, 64)))
        self.write_asset("tail.png", good + b"junk")
        self.write_asset("interlaced.png", png(64, 64, interlace=1))
        self.write_asset("noiend.png", good[:-12])
        self.write_asset("ihdr12.png", B.PNG_SIGNATURE + chunk(b"IHDR", good[16:28]) + good[33:])
        rgb = struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)
        self.write_asset("notzlib.png", B.PNG_SIGNATURE + chunk(b"IHDR", rgb) + chunk(b"IDAT", b"not zlib data")
                         + chunk(b"IEND", b""))
        gray = struct.pack(">IIBBBBB", 4097, 4097, 1, 0, 0, 0, 0)
        self.write_asset("huge.png", B.PNG_SIGNATURE + chunk(b"IHDR", gray)
                         + chunk(b"IDAT", zlib.compress(b"\x00" * (4097 * 514))) + chunk(b"IEND", b""))
        empty = struct.pack(">IIBBBBB", 0, 0, 8, 2, 0, 0, 0)
        self.write_asset("zero.png", B.PNG_SIGNATURE + chunk(b"IHDR", empty) + chunk(b"IDAT", zlib.compress(b""))
                         + chunk(b"IEND", b""))
        self.write_asset("big.png", good[:-12] + chunk(b"tEXt", b"x" * (5 * 1024 * 1024)) + good[-12:])
        (self.root / "assets" / "link.png").symlink_to(self.root / "assets" / "icon.png")
        for value, fragment in (("./assets/wide.png", "square"),
                                ("./assets/tiny.png", "at least 48x48"),
                                ("./assets/icon.jpg", ".png file"),
                                ("./assets/cut.png", "cut off"),
                                ("./assets/crc.png", "damaged"),
                                ("./assets/liar.png", "does not match its size"),
                                ("./assets/tail.png", "cut off"),
                                ("./assets/noiend.png", "end with IEND"),
                                ("./assets/ihdr12.png", "end with IEND"),
                                ("./assets/notzlib.png", "cannot be inflated"),
                                ("./assets/huge.png", "limit is 4096"),
                                ("./assets/zero.png", "size is zero"),
                                ("./assets/big.png", "the limit is 5 MiB"),
                                ("./assets/interlaced.png", "interlaced"),
                                ("./assets\\icon.png", "backslash"),
                                ("./assets/ icon.png", "outer spaces"),
                                ("./assets/i\x01con.png", "control character"),
                                ("./assets/link.png", "symbolic link"),
                                ("./assets/../assets/icon.png", "inside the plugin folder"),
                                ("assets/icon.png", "starts with ./"),
                                ("./assets/icon.png/", "starts with ./"),
                                ("./assets/missing.png", "does not exist"),
                                ("./assets", "must point at a file"),
                                ("./assets/ic\x00on.png", "control character")):
            with self.subTest(value=value):
                self.assert_error(self.check(self.ui(logo=value)), fragment)

    def test_entries_must_differ_in_more_than_case(self):
        self.write_asset("Icon.png", png(64, 64))
        if (self.root / "assets" / "Icon.png").samefile(self.root / "assets" / "icon.png"):
            self.skipTest("case-insensitive file system")
        self.assert_error(self.check(self.ui(composerIcon="./assets/Icon.png")), "differ only in case")

    def test_refused_fields(self):
        for key in ("apps", "hooks", "skills"):
            with self.subTest(key=key):
                self.assert_error(self.check(lambda m: m.update({key: "./x"})), key + ":")
        self.assert_error(self.check(self.ui(screenshots=["./assets/icon.png"])), "screenshots_not_allowed")
        self.assert_error(self.check(lambda m: m["extensions"]["com.openai"].update(review={})), "dashboard")
        self.assert_error(self.check(lambda m: m["extensions"]["com.openai"]["publication"].update(countries=[])),
                          "availability")
        self.assert_error(self.check(lambda m: m.update(homepage="https://www.example.com")), "not checked")
        self.assert_error(self.check(lambda m: m["author"].update(test_credentials="x")), "never put reviewer")
        self.assert_error(self.check(lambda m: m["extensions"]["com.openai"].update(reviewer_instructions="x")),
                          "never put reviewer")

    def test_release_notes_are_required(self):
        self.assert_error(self.check(lambda m: m.pop("extensions")), "release_notes is required")
        self.assert_error(self.check(lambda m: m["extensions"]["com.openai"].update(publication={})),
                          "release_notes is required")

    def test_malformed_input_is_an_error_not_a_crash(self):
        changes = [
            lambda m: m.update(interface=[]), lambda m: m.update(author="Intuizi"),
            lambda m: m.update(name=["x"]), lambda m: m.update(version=1), lambda m: m.update(description=5),
            lambda m: m.update(extensions=[]), lambda m: m["extensions"].update({"com.openai": []}),
            lambda m: m["extensions"]["com.openai"].update(publication=[]),
            lambda m: m["extensions"]["com.openai"]["publication"].update(release_notes=5),
            self.ui(capabilities=[5]), self.ui(defaultPrompt={}), self.ui(defaultPrompt=5),
            self.ui(defaultPrompt=""), self.ui(category=["x"]), self.ui(logo=5), self.ui(websiteURL=5),
        ]
        for i, change in enumerate(changes):
            with self.subTest(change=i):
                self.assertNotEqual(self.check(change).errors, [])
        for raw in (b"", b"[]", b"null", b"{", b"\xff\xfe{}"):
            with self.subTest(raw=raw):
                self.assertNotEqual(self.check_raw(raw).errors, [])



@unittest.skipUnless(shutil.which("git"), "git is not installed")
class MainTest(unittest.TestCase):
    """The command line, in a throwaway git repository shaped like this one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        # Keep the caller's git setup away from the throwaway repository: a hook's GIT_DIR
        # or GIT_INDEX_FILE would point git at the real one, and global hooks or templates
        # would run here.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=str(self.tmp))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.tmp / "repo"
        self.plugin = self.repo / "plugins" / "intuizi"
        self.manifest = self.plugin / B.MANIFEST
        for rel, data in {
            B.MANIFEST: (json.dumps(VALID, indent=2) + "\n").encode("utf-8"),
            B.CLAUDE_MANIFEST: json.dumps({"name": "intuizi", "version": VALID["version"]}).encode("utf-8"),
            B.MCP_SOURCE: MCP_DECLARATION.encode("utf-8"),
            "assets/icon.png": png(64, 64),
        }.items():
            (self.plugin / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.plugin / rel).write_bytes(data)
        (self.repo / ".gitattributes").write_text("* text=auto eol=lf\n*.png binary\n", encoding="utf-8")
        self.git("init", "-q")
        self.commit("fixture")
        self.out = self.tmp / "dist"
        for name, value in (("REPO_ROOT", self.repo), ("PLUGIN_ROOT", self.plugin)):
            patcher = mock.patch.object(B, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, *args, top=None):
        subprocess.run(["git", "-C", str(top or self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                       check=True, capture_output=True)

    def commit(self, message, top=None):
        self.git("add", "-A", top=top)
        self.git("commit", "-q", "-m", message, top=top)

    def run_main(self, *args):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = B.main(["--out", str(self.out), *args])
        return code, stderr.getvalue()

    def edit_manifest(self, old, new):
        self.manifest.write_bytes(self.manifest.read_bytes().replace(old, new))

    def release_zip(self, uncommitted=False):
        return self.out / B.zip_name(VALID["version"], uncommitted)

    def test_clean_tree_builds(self):
        self.assertEqual(self.run_main(), (0, ""))
        self.assertTrue(self.release_zip().exists())

    def test_uncommitted_edit_is_refused_and_the_old_zip_removed(self):
        self.assertEqual(self.run_main()[0], 0)
        self.edit_manifest(b"First test release.", b"Edited release.")
        code, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("plugins/intuizi/.codex-plugin/plugin.json", err)
        self.assertFalse(self.release_zip().exists())

    def test_untracked_icon_is_refused(self):
        (self.plugin / "assets" / "new.png").write_bytes(png(64, 64))
        self.edit_manifest(b'"composerIcon": "./assets/icon.png"', b'"composerIcon": "./assets/new.png"')
        self.git("add", str(self.manifest))
        self.git("commit", "-q", "-m", "point at an untracked icon")
        code, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("plugins/intuizi/assets/new.png", err)

    def test_line_ending_conversion_is_caught(self):
        # git stores LF and keeps the CRLF copy on disk, so git status reports nothing.
        self.edit_manifest(b"First test release.", b"Edited release.")
        self.manifest.write_bytes(self.manifest.read_bytes().replace(b"\n", b"\r\n"))
        self.commit("save with CRLF")
        code, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("plugins/intuizi/.codex-plugin/plugin.json differs from the last commit only in line endings", err)

    def test_check_writes_nothing(self):
        self.assertEqual(self.run_main("--check"), (0, ""))
        self.assertFalse(self.out.exists())

    def test_without_git_the_build_is_refused(self):
        shutil.rmtree(self.repo / ".git")
        code, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("cannot check with git", err)

    def test_repository_in_a_subfolder(self):
        # As when this repository is vendored into a larger one.
        outer = self.tmp / "outer"
        inner = outer / "vendor" / "plugin"
        shutil.copytree(self.repo, inner, ignore=shutil.ignore_patterns(".git"))
        self.git("init", "-q", top=outer)
        self.commit("vendor", top=outer)
        with mock.patch.object(B, "REPO_ROOT", inner), \
                mock.patch.object(B, "PLUGIN_ROOT", inner / "plugins" / "intuizi"):
            self.assertEqual(self.run_main(), (0, ""))

    def test_check_never_deletes_a_zip(self):
        self.assertEqual(self.run_main()[0], 0)
        self.edit_manifest(b'"Data & Analytics"', b'"Analytics"')
        self.assertEqual(self.run_main("--check")[0], 1)
        self.assertTrue(self.release_zip().exists())

    def test_allow_dirty_writes_its_own_file(self):
        self.edit_manifest(b"First test release.", b"Edited release.")
        self.assertEqual(self.run_main("--allow-dirty")[0], 0)
        self.assertTrue(self.release_zip(uncommitted=True).exists())
        self.assertFalse(self.release_zip().exists())

    def test_failed_allow_dirty_run_removes_only_its_own_zip(self):
        self.assertEqual(self.run_main()[0], 0)
        self.edit_manifest(b"First test release.", b"Edited release.")
        self.assertEqual(self.run_main("--allow-dirty")[0], 0)
        self.edit_manifest(b'"Data & Analytics"', b'"Analytics"')
        self.assertEqual(self.run_main("--allow-dirty")[0], 1)
        self.assertTrue(self.release_zip().exists())
        self.assertFalse(self.release_zip(uncommitted=True).exists())

    def test_failed_release_run_removes_both_zips(self):
        self.assertEqual(self.run_main()[0], 0)
        self.edit_manifest(b"First test release.", b"Edited release.")
        self.assertEqual(self.run_main("--allow-dirty")[0], 0)
        self.edit_manifest(b'"Data & Analytics"', b'"Analytics"')
        self.assertEqual(self.run_main()[0], 1)
        self.assertFalse(self.release_zip().exists())
        self.assertFalse(self.release_zip(uncommitted=True).exists())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Validate the ChatGPT plugin package and build the ZIP to upload to OpenAI.

The package is plugins/intuizi/.codex-plugin/plugin.json plus the icon files it
references. The ZIP holds exactly those files. The Claude files in the same
folder (.claude-plugin/, .mcp.json, README.md, skills/) never reach OpenAI, so
OpenAI's default component discovery cannot pick anything up by accident.

The script checks every field this package uses against OpenAI's rules and
refuses all other fields, so no unchecked field can reach an upload. Add a
check here before you use a new field. The rules come from:
  https://developers.openai.com/plugins/deploy/submission
  https://developers.openai.com/plugins/deploy/submission-errors

Usage:
  python3 scripts/build-openai-zip.py                validate, then write dist/<name>-<version>.zip
  python3 scripts/build-openai-zip.py --check        validate only
  python3 scripts/build-openai-zip.py --allow-dirty  test build from uncommitted files, written as
                                                     dist/<name>-<version>-uncommitted.zip (never upload it)

Standard library only, Python 3.8 or later.
"""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import unicodedata
import urllib.parse
import zipfile
import zlib
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "intuizi"
MANIFEST = ".codex-plugin/plugin.json"
# Both listings carry one version: the Claude manifest and MANIFEST must agree.
CLAUDE_MANIFEST = ".claude-plugin/plugin.json"

# OpenAI assigned this package name when the plugin was first published, and an
# update must keep it.
PUBLISHED_NAME = "app-6ab5004a37dc81918472cf526729e745"

# The same fixed timestamp and file mode as OpenAI's own release ZIP, so the
# same sources always build the same bytes.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o100644

CATEGORIES = (
    "Productivity", "Creativity", "Developer Tools", "Business & Operations", "Data & Analytics",
    "Communication", "Education & Research", "Security", "Finance", "Healthcare", "Travel",
    "Entertainment", "Other",
)
URL_FIELDS = ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL")
REQUIRED_ICONS = ("logo", "composerIcon")
OPTIONAL_ICONS = ("logoDark", "composerIconDark")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# The fields this script checks. Every other field is refused.
TOP_LEVEL_FIELDS = {"name", "version", "description", "author", "interface", "extensions"}
AUTHOR_FIELDS = {"name", "email", "url"}
INTERFACE_FIELDS = {
    "displayName", "shortDescription", "longDescription", "developerName", "category",
    "capabilities", "defaultPrompt",
} | set(URL_FIELDS) | set(REQUIRED_ICONS) | set(OPTIONAL_ICONS)

# Fields refused for a reason of their own.
REFUSED = {
    "mcpServers": "the MCP server is connected in the OpenAI dashboard, and OpenAI's export of "
                  "version 1.0.0 declares none. The update flow cannot change an MCP server URL, and "
                  "the .mcp.json in this folder uses Claude's format, which OpenAI rejects",
    "apps": "OpenAI does not accept app references (apps, .app.json) in a ZIP for the plugin directory",
    "hooks": "OpenAI does not accept lifecycle hooks in a ZIP for the plugin directory",
    "skills": "the published ChatGPT version has no skills, and this script does not check "
              "OpenAI's skill rules yet",
    "screenshots": "OpenAI accepts screenshots only when the MCP server reports a UI output "
                   "template (screenshots_not_allowed), and the Intuizi server has none",
    "review": "review material (test cases, the demo recording, and commerce details) belongs in "
              "the OpenAI dashboard, not in this public repository. A package that leaves it out "
              "keeps the saved values",
    "countries": "leave countries out to keep the availability that is set in the OpenAI dashboard",
    "test_credentials": "never put reviewer credentials in the package, enter them in the OpenAI dashboard",
    "reviewer_instructions": "never put reviewer instructions in the package, enter them in the OpenAI dashboard",
}

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
MENTION_RE = re.compile(r"(?:^|\s)@\w")


class Package:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest = {}
        self.files = {MANIFEST}
        self.errors = []

    def error(self, message):
        self.errors.append(message)


# --- values --------------------------------------------------------------------

def bad_character(value, multiline):
    """Return the first character OpenAI does not accept in text, or None.

    That is every control character, invisible formatting character, and Unicode
    line or paragraph separator. A line break is allowed only in multiline fields.
    """
    for ch in value:
        if ch == "\n" and multiline:
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp"):
            return ch
    return None


def check_string(pkg, value, where, limit=None, multiline=False):
    if not isinstance(value, str) or not value.strip():
        pkg.error(f"{where} must be a non-empty string")
        return None
    if limit is not None and len(value) > limit:
        pkg.error(f"{where} has {len(value)} characters, the limit is {limit}")
    ch = bad_character(value, multiline)
    if ch is not None:
        rest = "" if multiline else ". It must be one line"
        pkg.error(f"{where} contains the character U+{ord(ch):04X}, which OpenAI does not accept{rest}")
    return value


def check_text(pkg, obj, key, where, limit=None, required=True, multiline=False):
    if obj.get(key) is None:
        if required:
            pkg.error(f"{where}{key} is required")
        return None
    return check_string(pkg, obj[key], where + key, limit, multiline)


def check_url(pkg, value, where, limit):
    if not isinstance(value, str) or not value:
        pkg.error(f"{where} must be a URL")
        return
    if len(value) > limit:
        pkg.error(f"{where} has {len(value)} characters, the limit is {limit}")
    if any(ch.isspace() or ch in "[]" or bad_character(ch, False) for ch in value):
        pkg.error(f"{where} contains a space, a control character, or a square bracket: {value!r}")
        return
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
    except ValueError:
        pkg.error(f"{where} is not a valid URL: {value!r}")
        return
    if parts.scheme != "https" or not host:
        pkg.error(f"{where} must be an https URL with a host, got {value!r}")
    elif "@" in parts.netloc:
        pkg.error(f"{where} must not embed credentials")


def check_fields(pkg, obj, allowed, where):
    for key in sorted(set(obj) - allowed):
        reason = REFUSED.get(key, "is not checked by this script yet. Add a check here before you use it")
        pkg.error(f"{where}{key}: {reason}" if key in REFUSED else f"{where}{key} {reason}")


# --- files ---------------------------------------------------------------------

def package_file(pkg, value, where):
    """Resolve a ./-relative manifest path to a regular file in the plugin folder, or record an error."""
    if not isinstance(value, str) or not value.startswith("./") or value.endswith("/"):
        pkg.error(f"{where} must be a file path that starts with ./, got {value!r}")
        return None
    parts = value[2:].split("/")
    if any(part in ("", ".", "..") for part in parts):
        pkg.error(f"{where} must name a file inside the plugin folder, got {value!r}")
        return None
    if "\\" in value or bad_character(value, False) or any(part != part.strip() for part in parts):
        pkg.error(f"{where} contains a backslash, a control character, or a name with outer spaces: {value!r}")
        return None
    rel = PurePosixPath(*parts)
    path = pkg.root.joinpath(*parts)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        pkg.error(f"{where} points at {value}, which does not exist")
        return None
    except (OSError, ValueError, RuntimeError) as exc:
        pkg.error(f"{where} cannot be read: {value!r} ({exc.__class__.__name__})")
        return None
    if resolved != path:
        pkg.error(f"{where} must not go through a symbolic link: {value}")
        return None
    if not resolved.is_file():
        pkg.error(f"{where} must point at a file: {value}")
        return None
    return rel


def read_png(data):
    """Decode a PNG far enough to know OpenAI can decode it.

    Returns (width, height), or a string that says what is wrong. It checks the
    chunk layout and every CRC, inflates the image data, and checks its length.
    """
    if data[:8] != PNG_SIGNATURE:
        return "it is not a PNG image"
    chunks, pos = [], 8
    while pos < len(data):
        if pos + 12 > len(data):
            return "it is cut off"
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            return "it is cut off"
        if struct.unpack(">I", crc)[0] != zlib.crc32(kind + body):
            return f"its {kind.decode('latin-1')} chunk is damaged"
        chunks.append((kind, body))
        pos += 12 + length
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13 or chunks[-1][0] != b"IEND":
        return "it does not start with IHDR and end with IEND"
    width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if channels is None or interlace:
        return "it is interlaced or uses an unknown color type, save it as a plain PNG"
    if not width or not height:
        return "its size is zero"
    if width > 4096 or height > 4096:
        return width, height  # too large to be worth inflating, check_icon reports the limit
    expected = height * (1 + (width * channels * depth + 7) // 8)
    inflater = zlib.decompressobj()
    try:
        pixels = inflater.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"), expected + 1)
    except zlib.error:
        return "its image data cannot be inflated"
    if len(pixels) != expected or not inflater.eof:
        return "its image data does not match its size"
    return width, height


def check_icon(pkg, value, where):
    # OpenAI also takes JPEG, WebP, and SVG. This package keeps to PNG, which is
    # the one format this script reads.
    rel = package_file(pkg, value, where)
    if rel is None:
        return
    if rel.suffix != ".png":
        pkg.error(f"{where} must be a .png file: {value}")
        return
    try:
        data = (pkg.root / rel).read_bytes()
    except OSError as exc:
        pkg.error(f"{where} cannot be read: {value} ({exc.__class__.__name__})")
        return
    if len(data) > MAX_IMAGE_BYTES:
        pkg.error(f"{where} is {len(data)} bytes, the limit is 5 MiB")
        return
    size = read_png(data)
    if isinstance(size, str):
        pkg.error(f"{where} cannot be decoded, because {size}: {value}")
        return
    width, height = size
    if width != height:
        pkg.error(f"{where} must be square, it is {width}x{height}")
    elif width < 48:
        pkg.error(f"{where} must be at least 48x48, it is {width}x{height}")
    elif width > 4096:
        pkg.error(f"{where} is {width}x{height}, the limit is 4096 pixels on either side")
    pkg.files.add(rel.as_posix())


# --- manifest sections -----------------------------------------------------------

def check_identity(pkg, m):
    if m.get("name") != PUBLISHED_NAME:
        pkg.error(f"name must stay {PUBLISHED_NAME!r}, the package name OpenAI assigned, got {m.get('name')!r}")
    version = m.get("version")
    if not isinstance(version, str) or len(version) > 64 or not SEMVER_RE.fullmatch(version):
        pkg.error(f"version must be a semantic version such as 1.0.2, got {version!r}")
    else:
        check_shared_version(pkg, version)
    # The submission field table says 4,000, but the upload check (plugin_description_too_long)
    # says 1,024. The listing text itself is interface.longDescription.
    check_text(pkg, m, "description", "", 1024, multiline=True)
    author = m.get("author")
    if not isinstance(author, dict):
        pkg.error("author must be an object with a name")
    else:
        check_fields(pkg, author, AUTHOR_FIELDS, "author.")
        check_text(pkg, author, "name", "author.", 120)
        check_text(pkg, author, "email", "author.", 320, required=False)
        if author.get("url") is not None:
            check_url(pkg, author["url"], "author.url", 2048)


def check_shared_version(pkg, version):
    try:
        claude = json.loads((pkg.root / CLAUDE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pkg.error(f"cannot read the version in {CLAUDE_MANIFEST}: {exc.__class__.__name__}")
        return
    claude_version = claude.get("version") if isinstance(claude, dict) else None
    if claude_version != version:
        pkg.error(f"version {version} differs from {claude_version!r} in {CLAUDE_MANIFEST}. "
                  "Both listings share one version, so raise both together")


def check_interface(pkg, m):
    ui = m.get("interface")
    if not isinstance(ui, dict):
        pkg.error("interface must be an object")
        return
    w = "interface."
    check_fields(pkg, ui, INTERFACE_FIELDS, w)
    check_text(pkg, ui, "displayName", w, 30)
    check_text(pkg, ui, "shortDescription", w, 30)
    check_text(pkg, ui, "longDescription", w, 4000, multiline=True)
    check_text(pkg, ui, "developerName", w, 80)
    if ui.get("category") not in CATEGORIES:
        pkg.error(f"interface.category must be one of {', '.join(CATEGORIES)}, got {ui.get('category')!r}")

    capabilities = ui.get("capabilities")
    if capabilities is None:
        pkg.error("interface.capabilities is required, use [] when there are none")
    elif not isinstance(capabilities, list):
        pkg.error("interface.capabilities must be a list of strings")
    else:
        if len(capabilities) > 20:
            pkg.error(f"interface.capabilities has {len(capabilities)} entries, the limit is 20")
        for i, capability in enumerate(capabilities):
            check_string(pkg, capability, f"interface.capabilities[{i}]", 120)

    # All four links are required, because this plugin has an MCP app.
    for field in URL_FIELDS:
        if ui.get(field) is None:
            pkg.error(f"interface.{field} is required")
        else:
            check_url(pkg, ui[field], f"interface.{field}", 1024)

    if ui.get("defaultPrompt") is not None:
        check_prompts(pkg, ui["defaultPrompt"])

    for field in REQUIRED_ICONS:
        if ui.get(field) is None:
            pkg.error(f"interface.{field} is required for this package format, for example ./assets/icon.png")
    for field in REQUIRED_ICONS + OPTIONAL_ICONS:
        if ui.get(field) is not None:
            check_icon(pkg, ui[field], f"interface.{field}")


def check_prompts(pkg, prompts):
    prompts = [prompts] if isinstance(prompts, str) else prompts
    if not isinstance(prompts, list):
        pkg.error("interface.defaultPrompt must be a string or a list of strings")
        return
    if len(prompts) > 3:
        pkg.error(f"interface.defaultPrompt has {len(prompts)} prompts, the limit is 3")
    seen = set()
    for i, prompt in enumerate(prompts):
        where = f"interface.defaultPrompt[{i}]"
        if check_string(pkg, prompt, where, 128) is None:
            continue
        if MENTION_RE.search(prompt):
            pkg.error(f"{where} must not @mention an MCP server")
        key = " ".join(unicodedata.normalize("NFKC", prompt).split())
        if key in seen:
            pkg.error(f"{where} repeats an earlier prompt")
        seen.add(key)


def check_extensions(pkg, m):
    notes_missing = ("extensions.com.openai.publication.release_notes is required: OpenAI needs release "
                     "notes for every submission, and without them the previous version's notes carry over")
    extensions = m.get("extensions")
    if not isinstance(extensions, dict):
        pkg.error(notes_missing if extensions is None else "extensions must be an object")
        return
    check_fields(pkg, extensions, {"com.openai"}, "extensions.")
    openai = extensions.get("com.openai")
    if not isinstance(openai, dict):
        pkg.error(notes_missing if openai is None else "extensions.com.openai must be an object")
        return
    check_fields(pkg, openai, {"publication"}, "extensions.com.openai.")
    publication = openai.get("publication")
    if not isinstance(publication, dict):
        pkg.error(notes_missing if publication is None else "extensions.com.openai.publication must be an object")
        return
    check_fields(pkg, publication, {"release_notes"}, "extensions.com.openai.publication.")
    if publication.get("release_notes") is None:
        pkg.error(notes_missing)
    else:
        check_string(pkg, publication["release_notes"], "extensions.com.openai.publication.release_notes",
                     multiline=True)


def validate(pkg):
    path = pkg.root / MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pkg.error(f"{MANIFEST} is missing")
        return
    except UnicodeDecodeError:
        pkg.error(f"{MANIFEST} must be UTF-8 text")
        return
    except (OSError, ValueError) as exc:
        pkg.error(f"{MANIFEST} is not valid JSON: {exc}")
        return
    if not isinstance(manifest, dict):
        pkg.error(f"{MANIFEST} must hold a JSON object")
        return
    pkg.manifest = manifest
    # Every object below refuses unknown keys, and every list holds strings, so a key
    # such as test_credentials is refused wherever it appears.
    check_fields(pkg, manifest, TOP_LEVEL_FIELDS, "")
    check_identity(pkg, manifest)
    check_interface(pkg, manifest)
    check_extensions(pkg, manifest)
    folded = {}
    for rel in sorted(pkg.files):
        key = unicodedata.normalize("NFC", rel).casefold()
        if key in folded:
            pkg.error(f"{rel} and {folded[key]} differ only in case, which OpenAI rejects")
        folded[key] = rel


# --- build -----------------------------------------------------------------------

def zip_name(version, uncommitted=False):
    return f"{PUBLISHED_NAME}-{version}{'-uncommitted' if uncommitted else ''}.zip"


def build(pkg, out_dir, uncommitted=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / zip_name(pkg.manifest["version"], uncommitted)
    partial = target.with_name(target.name + ".partial")
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            for rel in sorted(pkg.files):
                info = zipfile.ZipInfo(rel, date_time=ZIP_DATE)
                info.create_system = 3  # Unix, so the file mode below is kept
                info.external_attr = ZIP_MODE << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (pkg.root / rel).read_bytes())
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def git(*args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, check=True).stdout


def uncommitted(pkg):
    """Compare every packaged file with the last commit, byte for byte.

    git status is not enough: it hides line-ending conversion and files marked
    assume-unchanged. Returns (changed, line_endings, problem): the files that differ
    from the commit or are not in it, the files that differ only in line endings, and
    the reason git could not check, or None.
    """
    try:
        git("rev-parse", "--verify", "HEAD")
    except OSError:
        return [], [], "git is not installed"
    except subprocess.CalledProcessError as exc:
        lines = exc.stderr.decode("utf-8", "replace").strip().splitlines()
        return [], [], lines[0] if lines else "git rev-parse failed"
    changed, line_endings = [], []
    for rel in sorted(pkg.files):
        try:
            path = (pkg.root / rel).relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return [], [], f"{rel} is outside the repository"
        try:
            # ./ makes git read the path from REPO_ROOT, also when the repository is a subfolder.
            committed = git("cat-file", "blob", f"HEAD:./{path}")
        except subprocess.CalledProcessError:
            committed = None
        on_disk = (pkg.root / rel).read_bytes()
        if committed == on_disk:
            continue
        if committed is not None and committed == on_disk.replace(b"\r\n", b"\n"):
            line_endings.append(path)
        else:
            changed.append(path)
    return changed, line_endings, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the ChatGPT plugin package and build its upload ZIP.")
    parser.add_argument("--check", action="store_true", help="validate only, do not write a ZIP")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="test build from uncommitted files, written as <name>-<version>-uncommitted.zip")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dist",
                        help="folder for the ZIP (default: dist/ in the repository)")
    args = parser.parse_args(argv)
    out_dir = args.out.resolve()

    pkg = Package(PLUGIN_ROOT)
    validate(pkg)
    version = pkg.manifest.get("version")
    print(f"ChatGPT plugin package {pkg.manifest.get('name', '?')} {version or '?'} "
          f"({PLUGIN_ROOT.relative_to(REPO_ROOT).as_posix()}/{MANIFEST})")

    changed, line_endings, problem = [], [], None
    if not pkg.errors and not args.check:
        changed, line_endings, problem = uncommitted(pkg)
        if not args.allow_dirty:
            if problem:
                pkg.error(f"cannot check with git that the packaged files are committed ({problem}). Run "
                          "this inside the repository, or pass --allow-dirty for a test build")
            for path in line_endings:
                pkg.error(f"{path} differs from the last commit only in line endings, so git has nothing "
                          f"to commit. Delete the file, then run: git checkout -- {path}")
            if changed:
                pkg.error("these files differ from the last commit, so commit them first: " + ", ".join(changed))

    if pkg.errors:
        for error in pkg.errors:
            print(f"  error: {error}", file=sys.stderr)
        # Never leave an older ZIP of this version where someone expects the new one.
        if not args.check and isinstance(version, str) and SEMVER_RE.fullmatch(version):
            for uncommitted_build in ((True,) if args.allow_dirty else (False, True)):
                (out_dir / zip_name(version, uncommitted_build)).unlink(missing_ok=True)
        print(f"{len(pkg.errors)} error(s), no ZIP written", file=sys.stderr)
        return 1
    if args.check:
        print("valid")
        return 0

    target = build(pkg, out_dir, uncommitted=args.allow_dirty)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    try:
        commit = git("rev-parse", "--short", "HEAD").decode().strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    if args.allow_dirty:
        differ = problem or ", ".join(changed + line_endings) or "none"
        source = f"test build, never upload it (files that differ from commit {commit}: {differ})"
    else:
        source = f"commit {commit}"
    print(f"built {target}")
    # Another zlib (such as zlib-ng) writes other bytes from the same files.
    print(f"  {target.stat().st_size} bytes, sha256 {digest}, zlib {zlib.ZLIB_RUNTIME_VERSION}, {source}")
    for rel in sorted(pkg.files):
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

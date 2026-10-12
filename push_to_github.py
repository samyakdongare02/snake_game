#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_to_github.py - publish this project to GitHub in one command.

The script has two interchangeable back-ends:

* ``git`` - drives the normal ``git`` command line (preferred when Git is
  installed; it honours ``.gitignore`` natively).
* ``api`` - talks straight to the GitHub REST API using **only the standard
  library**, so it also works on a machine where Git is not installed at all
  (like the sandbox this was written in).

Nothing secret is ever written to disk: the token comes from ``--token``, the
``GITHUB_TOKEN`` / ``GH_TOKEN`` environment variable, or an interactive prompt
(hidden input).

Typical use
-----------
    # Preview exactly what would be uploaded (no network, no token needed)
    python push_to_github.py --dry-run

    # Easiest: provide a token and let the script do the rest
    set GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx          (Windows)
    export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx       (bash)
    python push_to_github.py

    # Explicit, non-interactive
    python push_to_github.py --owner samyakdongare02 \
        --repo snake_game --branch main --token ghp_xxx

Authentication
--------------
Three routes, in order of preference:

1. ``--ssh`` -- push over SSH, which needs **no token and no password**.  All
   that is required is an SSH keypair whose *public* half is registered on the
   repository as a deploy key with write access.  ``--ssh-key`` points at the
   private key file; when it is omitted, your normal SSH configuration
   (``~/.ssh/config``, the agent, default identities) is used.  This is the
   tightest option available: a deploy key opens exactly one repository and is
   revoked by deleting it.

       ssh-keygen -t ed25519 -f ~/.ssh/snake_deploy_ed25519 -N ""
       # paste ~/.ssh/snake_deploy_ed25519.pub into
       #   <repo> -> Settings -> Deploy keys -> Add deploy key
       #   and tick "Allow write access"
       python push_to_github.py --ssh --ssh-key ~/.ssh/snake_deploy_ed25519

   A deploy key cannot create a repository, so the repository must exist first.

2. A token, from ``--token``, ``$GITHUB_TOKEN``, ``$GH_TOKEN`` or
   ``$GITHUB_PAT``.

   * Classic token: the ``repo`` scope (can also create repositories).
   * Fine-grained token: *Contents: Read and write*, plus *Administration: Read
     and write* only if the script must create the repository.  Note that
     fine-grained tokens frequently cannot create repositories at all -- if the
     script reports HTTP 403 on creation, create the repository by hand (empty,
     no README) and re-run with ``--no-create``.

   Create tokens at <https://github.com/settings/tokens>.

3. ``--method api`` -- the same token, but over the REST API instead of the git
   command line, so it also works where Git is not installed.

Nothing secret is stored: a token is used for a single command and never lands
in ``.git/config`` or the remote URL, and an SSH key stays wherever
``--ssh-key`` points.  Neither is ever committed.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
USER_AGENT = "snake-push-to-github/1.1"
DEFAULT_OWNER = "samyakdongare02"
DEFAULT_REPO = "snake_game"
DEFAULT_BRANCH = "main"
DEFAULT_MESSAGE = "Snake: Kivy Android game with signed-APK CI"
#: Commits are attributed to this identity (overridable with --author-name /
#: --email).  Nothing here is a secret.
DEFAULT_AUTHOR = "samyakdongare02"
DEFAULT_EMAIL = "samyakdongare02@gmail.com"

# Everything is skipped unless a marker file proves we are at the project root.
ROOT_MARKERS = ("main.py", "snake_core.py", "buildozer.spec")

ALWAYS_SKIP_DIRS = {".git", "__pycache__", ".buildozer", "bin", ".venv", "venv"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
class GithubError(Exception):
    def __init__(self, status, message):
        super().__init__("HTTP %s: %s" % (status, message))
        self.status = status
        self.message = message


def find_root(start):
    """Walk upwards until we find the project root."""
    cur = os.path.abspath(start)
    while True:
        if all(os.path.exists(os.path.join(cur, m)) for m in ROOT_MARKERS):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit(
                "Could not find the project root (looked for %s)."
                % ", ".join(ROOT_MARKERS))
        cur = parent


def load_gitignore(root):
    """Read .gitignore into a list of patterns (order matters)."""
    patterns = []
    path = os.path.join(root, ".gitignore")
    if not os.path.isfile(path):
        return patterns
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def is_ignored(rel_path, patterns):
    """Minimal but faithful-enough .gitignore matcher."""
    rel_path = rel_path.replace(os.sep, "/")
    parts = rel_path.split("/")
    name = parts[-1]
    decision = False
    for raw in patterns:
        negate = raw.startswith("!")
        pat = raw[1:] if negate else raw
        is_dir = pat.endswith("/")
        pat = pat.strip("/")
        if not pat:
            continue
        if is_dir:
            hit = any(fnmatch.fnmatch(p, pat) for p in parts[:-1]) \
                or fnmatch.fnmatch(name, pat)
        elif "/" in pat:
            hit = fnmatch.fnmatch(rel_path, pat)
        else:
            hit = fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_path, pat)
        if hit:
            decision = not negate
    return decision


def collect_files(root):
    """Return a sorted list of repo-relative paths to publish."""
    patterns = load_gitignore(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        # prune ignored / always-skipped directories in place
        keep = []
        for d in dirnames:
            rel = "%s/%s" % (rel_dir, d) if rel_dir else d
            if d in ALWAYS_SKIP_DIRS or is_ignored(rel + "/", patterns):
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)

        for fn in sorted(filenames):
            rel = "%s/%s" % (rel_dir, fn) if rel_dir else fn
            if is_ignored(rel, patterns):
                continue
            out.append(rel)
    return sorted(out)


def file_mode(path):
    return "100755" if os.name != "nt" and os.access(path, os.X_OK) else "100644"


def api(method, path, token, body=None):
    """Perform one GitHub REST call and return the decoded JSON (or {})."""
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            message = json.loads(raw).get("message", raw)
        except ValueError:
            message = raw
        raise GithubError(exc.code, message) from None
    except urllib.error.URLError as exc:
        raise SystemExit("Network error talking to GitHub: %s" % exc.reason)


def ensure_repo(owner, repo, token, private):
    """Create the repository if it does not exist. Returns its HTML url."""
    try:
        info = api("GET", "/repos/%s/%s" % (owner, repo), token)
        print("  repository already exists: %s" % info["html_url"])
        return info["html_url"]
    except GithubError as exc:
        if exc.status != 404:
            raise

    print("  creating repository %s/%s ..." % (owner, repo))
    try:
        kind = api("GET", "/users/%s" % owner, token).get("type")
    except GithubError:
        kind = "User"
    payload = {"name": repo, "private": bool(private), "auto_init": False,
               "has_issues": True, "has_wiki": False}
    try:
        if kind == "Organization":
            return api("POST", "/orgs/%s/repos" % owner, token, payload)["html_url"]
        return api("POST", "/user/repos", token, payload)["html_url"]
    except GithubError as exc:
        if exc.status not in (403, 404, 422):
            raise
        raise SystemExit(
            "GitHub refused the repository-creation request (HTTP %s: %s).\n"
            "Fine-grained tokens usually cannot create repositories.\n"
            "Two ways forward:\n"
            "  1. create an empty repo yourself at https://github.com/new\n"
            "     (no README, no .gitignore, no licence), then re-run with\n"
            "         --no-create\n"
            "  2. or regenerate the token with the *Administration: Read and\n"
            "     write* permission and run it again." % (exc.status, exc.message))


# ---------------------------------------------------------------------------
# back-end 1: the git command line
# ---------------------------------------------------------------------------
def _git(root, args, token=None, env=None):
    cmd = ["git"] + args
    shown = " ".join(a if (token is None or token not in a) else "***" for a in cmd)
    print("  $ %s" % shown)
    return subprocess.run(cmd, cwd=root, text=True, capture_output=True,
                          env=env)


def git_push(root, owner, repo, branch, message, create, private, token, dry,
             author_name=None, email=None, ssh=False, ssh_key=None):
    if not shutil.which("git"):
        raise SystemExit(
            "The 'git' command was not found. Install Git, or use the API "
            "back-end which needs no Git at all:\n"
            "    python push_to_github.py --method api --token <TOKEN>")
    if not os.path.isdir(os.path.join(root, ".git")):
        _git(root, ["init"])
    _git(root, ["add", "-A"])

    # Attribute the commit to the configured identity explicitly, so the result
    # does not depend on this machine's global git config.
    ident = []
    if author_name:
        ident += ["-c", "user.name=" + author_name]
    if email:
        ident += ["-c", "user.email=" + email]
    author = []
    if author_name and email:
        author = ["--author=%s <%s>" % (author_name, email)]

    res = _git(root, ident + ["commit", "-m", message] + author)
    blob = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0 and "nothing to commit" not in blob:
        print(blob)
        raise SystemExit("git commit failed.")

    _git(root, ["branch", "-M", branch])

    if ssh:
        url = "git@github.com:%s/%s.git" % (owner, repo)
    else:
        url = "https://github.com/%s/%s.git" % (owner, repo)
    if _git(root, ["remote", "get-url", "origin"]).returncode != 0:
        _git(root, ["remote", "add", "origin", url])
    else:
        _git(root, ["remote", "set-url", "origin", url])

    if create and token:
        ensure_repo(owner, repo, token, private)

    if dry:
        print("  [dry-run] would push %s to %s" % (branch, url))
        return "https://github.com/%s/%s" % (owner, repo)

    if ssh:
        # Build an explicit ssh command line so a push can never fall back to an
        # interactive password prompt (which would simply hang).  accept-new
        # trusts GitHub's host key on first contact instead of asking about it.
        command = "ssh -o StrictHostKeyChecking=accept-new"
        if ssh_key:
            key = os.path.abspath(os.path.expanduser(ssh_key))
            if not os.path.isfile(key):
                raise SystemExit("SSH private key not found: %s" % key)
            command += ' -i "%s" -o IdentitiesOnly=yes' % key
        print("  ssh command  : %s" % command)
        env = dict(os.environ, GIT_SSH_COMMAND=command,
                   GIT_TERMINAL_PROMPT="0")
        args = ["push", "-u", "origin", branch]
    elif token:
        # Authenticate just for this single command: the token is not stored
        # in .git/config and does not appear in the remote URL.
        basic = base64.b64encode(
            ("x-access-token:" + token).encode("utf-8")).decode("ascii")
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        args = ["-c", "credential.helper=",
                "-c", "http.extraheader=AUTHORIZATION: basic " + basic,
                "push", "-u", "origin", branch]
    else:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        args = ["push", "-u", "origin", branch]

    res = _git(root, args, token=token, env=env)
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    if res.returncode != 0:
        raise SystemExit("git push failed (see output above).")
    return "https://github.com/%s/%s" % (owner, repo)


# ---------------------------------------------------------------------------
# back-end 2: the GitHub REST API (no git required)
# ---------------------------------------------------------------------------
def api_push(root, owner, repo, branch, message, create, private, token, dry,
             author_name=None, email=None, prune=True):
    rels = collect_files(root)
    print("  %d file(s) selected:" % len(rels))
    for rel in rels:
        print("    + %s" % rel)
    if dry:
        return "https://github.com/%s/%s" % (owner, repo)

    # Fail fast with a clear message if the token is unusable.
    who = api("GET", "/user", token)
    print("  authenticated as %s" % who.get("login", "?"))

    if create:
        ensure_repo(owner, repo, token, private)

    # Find the tip of the branch (absent for a brand-new, empty repository).
    parent = None
    try:
        ref = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (owner, repo, branch),
                  token)
        parent = ref["object"]["sha"]
    except GithubError as exc:
        if exc.status != 404:
            raise

    base_tree = None
    if parent:
        base_tree = api("GET", "/repos/%s/%s/git/commits/%s"
                        % (owner, repo, parent), token)["tree"]["sha"]

    entries = []
    for rel in rels:
        with open(os.path.join(root, rel), "rb") as fh:
            data = fh.read()
        blob = api("POST", "/repos/%s/%s/git/blobs" % (owner, repo), token,
                   {"content": base64.b64encode(data).decode("ascii"),
                    "encoding": "base64"})
        entries.append({"path": rel, "mode": file_mode(os.path.join(root, rel)),
                        "type": "blob", "sha": blob["sha"]})
        print("    uploaded %-40s %7d bytes" % (rel, len(data)))

    # Mirror deletions so the remote matches the local tree exactly.  Deletions
    # stay recoverable (the previous commit remains in history), but
    # --no-prune disables them entirely for a purely additive push.
    if base_tree and prune:
        existing = api("GET", "/repos/%s/%s/git/trees/%s?recursive=1"
                       % (owner, repo, base_tree), token)
        keep = set(rels)
        for item in existing.get("tree", []):
            if item["type"] == "blob" and item["path"] not in keep:
                entries.append({"path": item["path"], "mode": item["mode"],
                                "type": "blob", "sha": None})
                print("    deleted  %s" % item["path"])
    elif base_tree:
        print("    (--no-prune: files missing locally are kept on the remote)")

    tree_body = {"tree": entries}
    if base_tree:
        tree_body["base_tree"] = base_tree
    tree = api("POST", "/repos/%s/%s/git/trees" % (owner, repo), token, tree_body)

    commit_body = {"message": message, "tree": tree["sha"]}
    if author_name and email:
        who = {"name": author_name, "email": email}
        commit_body["author"] = who
        commit_body["committer"] = who
    if parent:
        commit_body["parents"] = [parent]
    commit = api("POST", "/repos/%s/%s/git/commits" % (owner, repo), token,
                 commit_body)

    if parent:
        api("PATCH", "/repos/%s/%s/git/refs/heads/%s" % (owner, repo, branch),
            token, {"sha": commit["sha"], "force": False})
    else:
        api("POST", "/repos/%s/%s/git/refs" % (owner, repo), token,
            {"ref": "refs/heads/%s" % branch, "sha": commit["sha"]})

    print("  commit %s" % commit["sha"][:10])
    return "https://github.com/%s/%s" % (owner, repo)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Push this project to GitHub (git CLI or REST API).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Typical use")[-1].strip())
    ap.add_argument("--owner", default=DEFAULT_OWNER,
                    help="GitHub user/org (default: %s)" % DEFAULT_OWNER)
    ap.add_argument("--repo", default=DEFAULT_REPO,
                    help="repository name (default: %s)" % DEFAULT_REPO)
    ap.add_argument("--branch", default=DEFAULT_BRANCH,
                    help="branch to push (default: %s)" % DEFAULT_BRANCH)
    ap.add_argument("--message", default=DEFAULT_MESSAGE,
                    help="commit message")
    ap.add_argument("--author-name", default=DEFAULT_AUTHOR,
                    help="commit author name (default: %s)" % DEFAULT_AUTHOR)
    ap.add_argument("--email", default=DEFAULT_EMAIL,
                    help="commit author email (default: %s)" % DEFAULT_EMAIL)
    ap.add_argument("--token", default=None,
                    help="GitHub token (else $GITHUB_TOKEN/$GH_TOKEN, else ask)")
    ap.add_argument("--method", choices=("auto", "git", "api"), default="auto",
                    help="transport to use (default: auto)")
    ap.add_argument("--ssh", action="store_true",
                    help="push over SSH with an SSH key: no token needed")
    ap.add_argument("--ssh-key", default=None,
                    help="private key to use with --ssh (default: your "
                         "normal SSH configuration)")
    ap.add_argument("--private", action="store_true",
                    help="create the repository as private (public by default)")
    ap.add_argument("--no-create", action="store_true",
                    help="never try to create the repository")
    ap.add_argument("--no-prune", action="store_true",
                    help="never delete remote files that are absent locally")
    ap.add_argument("--no-input", action="store_true",
                    help="never prompt for a token (for scripts/CI)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be uploaded and stop")
    ap.add_argument("--root", default=None,
                    help="project root (default: auto-detected)")
    return ap.parse_args(argv)


def resolve_token(cli_token, method, dry, no_input=False):
    if cli_token:
        return cli_token
    for env_name in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        if os.environ.get(env_name):
            print("  using token from $%s" % env_name)
            return os.environ[env_name]
    if no_input or method == "git" or dry or not sys.stdin.isatty():
        return None
    sys.stderr.write("GitHub personal access token (input hidden, Ctrl+C to "
                     "abort): ")
    sys.stderr.flush()
    try:
        return getpass.getpass("").strip()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n")
        return None


def main(argv=None):
    args = parse_args(argv)
    root = find_root(args.root or os.path.dirname(os.path.abspath(__file__)))
    if args.ssh and args.token:
        raise SystemExit("--ssh and --token are mutually exclusive; pick one.")
    token = None if args.ssh else resolve_token(
        args.token, args.method, args.dry_run, args.no_input)

    if args.method == "auto":
        if args.ssh:
            method = "git"
        elif token:
            method = "api"
        elif shutil.which("git"):
            method = "git"
        else:
            method = "api"
    else:
        method = args.method

    if args.ssh and method != "git":
        raise SystemExit("--ssh needs the git back-end; drop --method api.")

    if method == "api" and not token and not args.dry_run:
        raise SystemExit(
            "The API back-end needs a token, and no Git is installed to fall "
            "back to.\n"
            "  * set one:  $env:GITHUB_TOKEN='ghp_xxx'   (PowerShell)\n"
            "              export GITHUB_TOKEN=ghp_xxx    (bash)\n"
            "  * or pass:  python push_to_github.py --token ghp_xxx\n"
            "  * or install Git and push with your normal credentials.\n"
            "A token is created at https://github.com/settings/tokens "
            "(classic 'repo' scope, or fine-grained 'Contents: Read and write').")

    print("Project root : %s" % root)
    print("Target       : https://github.com/%s/%s (%s)"
          % (args.owner, args.repo, args.branch))
    print("Commit as    : %s <%s>" % (args.author_name, args.email))
    print("Method       : %s%s" % (method, "  [dry-run]" if args.dry_run else ""))
    if args.ssh:
        print("SSH key      : %s"
              % (args.ssh_key or "(default SSH configuration)"))
    print("")

    create = not args.no_create
    if method == "api":
        url = api_push(root, args.owner, args.repo, args.branch, args.message,
                       create, args.private, token, args.dry_run,
                       args.author_name, args.email, not args.no_prune)
    else:
        url = git_push(root, args.owner, args.repo, args.branch, args.message,
                       create, args.private, token, args.dry_run,
                       args.author_name, args.email, args.ssh, args.ssh_key)

    print("")
    if args.dry_run:
        print("Dry run complete - nothing was sent to GitHub.")
    else:
        print("Done. Repository: %s" % url)
        print("The 'Android APK' workflow starts automatically on push; the "
              "signed APK appears under Actions -> Android APK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

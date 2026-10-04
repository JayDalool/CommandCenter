"""Workspace: GitHub identity, project files, uploads, attachments, Developer Unlock."""
import hashlib
import json
import os
import shutil
import stat
import tempfile
import unittest

from ccd import attachments as attach_mod
from ccd import config, github, registry, security
from ccd.files import FileError, Roots, is_protected_name

from .test_api import AUTH, HOST, JSON, TOKEN, ApiBase

DEV_SECRET = "d" * 43


class GitHubIdentity(unittest.TestCase):
    def test_ssh_https_and_bare_remotes_normalise(self):
        for remote in ("git@github.com:JayDalool/CommandCenter.git", "git@github.com:JayDalool/CommandCenter",
                       "https://github.com/JayDalool/CommandCenter.git", "https://github.com/JayDalool/CommandCenter",
                       "https://github.com/JayDalool/CommandCenter/", "ssh://git@github.com/JayDalool/CommandCenter.git",
                       "JayDalool/CommandCenter", " https://github.com/JayDalool/CommandCenter.git\n"):
            self.assertEqual(github.normalize(remote), "JayDalool/CommandCenter", remote)

    def test_malformed_and_foreign_remotes_have_no_identity(self):
        for remote in ("", "x", "https://x/12", "https://gitlab.com/a/b.git", "git@evil.com:a/b.git",
                       "https://github.com.evil.com/a/b", "https://github.com/a/b/c", "a/../b", "-o/r", "a b/c",
                       "https://github.com/JayDalool/..", None):
            self.assertIsNone(github.normalize(remote), remote)

    def test_urls_are_canonical_github(self):
        s = "JayDalool/SamVisionAI"
        self.assertEqual(github.repo_url(s), "https://github.com/JayDalool/SamVisionAI")
        self.assertEqual(github.pr_url(s, 94), "https://github.com/JayDalool/SamVisionAI/pull/94")
        self.assertEqual(github.commit_url(s, "ABCDEF1234"), "https://github.com/JayDalool/SamVisionAI/commit/abcdef1234")
        self.assertEqual(github.branch_url(s, "SV-056-x"), "https://github.com/JayDalool/SamVisionAI/tree/SV-056-x")
        self.assertEqual(github.actions_url(s), "https://github.com/JayDalool/SamVisionAI/actions")
        self.assertEqual(github.pr_ref_url("JayDalool/SamVisionAI#94"), github.pr_url(s, 94))
        for bad in (github.pr_url("x", 1), github.pr_url(s, 0), github.pr_url(s, "1"), github.commit_url(s, "zz"),
                    github.branch_url(s, "a b"), github.pr_ref_url("x#1"), github.repo_url("x")):
            self.assertIsNone(bad)

    def test_link_urls_never_trust_a_stored_github_url(self):
        self.assertEqual(github.link_url("github", "pr", "JayDalool/GauzeMate#3", "https://x/3"),
                         "https://github.com/JayDalool/GauzeMate/pull/3")
        self.assertIsNone(github.link_url("github", "pr", "x#3", "https://github.com/x/pull/3"))
        self.assertIsNone(github.link_url("url", "doc", "r", "javascript:alert(1)"))
        self.assertEqual(github.link_url("url", "doc", "r", "https://example.com/a"), "https://example.com/a")

    def test_every_registered_project_has_a_github_identity_and_root(self):
        for key, p in registry.PROJECTS.items():
            ident = github.identity(p["github"])
            self.assertIsNotNone(ident, key)
            self.assertTrue(ident["url"].startswith("https://github.com/"))
            self.assertTrue(os.path.isabs(p["root"]))
        self.assertEqual(registry.github_of("commandcenter"), "JayDalool/CommandCenter")

    def test_config_repo_that_contradicts_the_registry_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="cfg-"), "config.json")
        with open(path, "w") as f:
            json.dump({"projects": [{"key": "samvision", "repo": "JayDalool/x", "path": "/tmp"}]}, f)
        with self.assertRaises(registry.RegistryError):
            config.load(path)


class Files(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="ws-")
        self.root = os.path.join(self.base, "proj")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(os.path.join(self.root, ".git"))
        with open(os.path.join(self.root, ".git", "config"), "w") as f:
            f.write("[remote]\n")
        with open(os.path.join(self.root, "src", "a.py"), "w") as f:
            f.write("print('hi')\n")
        os.chmod(os.path.join(self.root, "src", "a.py"), 0o750)
        with open(os.path.join(self.root, ".env"), "w") as f:
            f.write("SECRET=1\n")
        with open(os.path.join(self.root, ".env.example"), "w") as f:
            f.write("SECRET=\n")
        with open(os.path.join(self.root, "bin.dat"), "wb") as f:
            f.write(b"\x00\x01\x02")
        with open(os.path.join(self.base, "outside.txt"), "w") as f:
            f.write("nope")
        os.symlink(os.path.join(self.base, "outside.txt"), os.path.join(self.root, "escape"))
        os.symlink(os.path.join(self.root, ".env"), os.path.join(self.root, "envlink"))
        self.r = Roots({"p": self.root}, upload_max=1024)

    def tearDown(self):
        shutil.rmtree(self.base)

    def code(self, fn, *a, **kw):
        try:
            fn(*a, **kw)
        except FileError as e:
            return e.status
        return 200

    def test_listing_hides_git_and_marks_secrets_and_escapes(self):
        out = self.r.list("p", "")
        names = {e["name"]: e for e in out["entries"]}
        self.assertNotIn(".git", names)
        self.assertTrue(names[".env"]["protected"])
        self.assertFalse(names[".env.example"]["protected"])
        self.assertEqual(names["escape"]["kind"], "outside")
        self.assertEqual(out["entries"][0]["name"], "src")  # folders first

    def test_unknown_project_and_arbitrary_roots_refused(self):
        self.assertEqual(self.code(self.r.list, "nope", ""), 404)
        self.assertEqual(self.code(self.r.list, "/etc", ""), 404)
        self.assertEqual(self.code(self.r.list, None, ""), 404)

    def test_traversal_in_every_spelling_is_refused(self):
        for bad in ("..", "../outside.txt", "src/../../outside.txt", "/etc/passwd", "src\\..\\..", "%2e%2e",
                    "src/%2e%2e/%2e%2e", "%2E%2E%2Foutside.txt", "a\x00b", "src/..%2f..", "..%5c..",
                    "src/\x1b[31m"):
            self.assertIn(self.code(self.r.read, "p", bad), (400, 403, 404), bad)
            self.assertIn(self.code(self.r.list, "p", bad), (400, 403, 404), bad)

    def test_symlink_escape_and_symlink_to_secret_refused(self):
        self.assertEqual(self.code(self.r.read, "p", "escape"), 403)
        self.assertEqual(self.code(self.r.read, "p", "envlink"), 403)

    def test_secret_files_and_git_are_never_readable(self):
        for bad in (".env", ".git/config", ".git", "x/.ssh/id_rsa", "server.pem", "a.key", ".env.local",
                    ".git-credentials", ".npmrc"):
            self.assertEqual(self.code(self.r.read, "p", bad), 403, bad)
        self.assertEqual(self.r.read("p", ".env.example")["text"], "SECRET=\n")
        for name in ("id_ed25519", "x.p12", ".netrc", "token", "a.token", "credentials.json"):
            self.assertTrue(is_protected_name(name), name)
        for name in (".env.example", "id_ed25519.pub", "keys.py", "README.md"):
            self.assertFalse(is_protected_name(name), name)

    def test_text_binary_and_large(self):
        t = self.r.read("p", "src/a.py")
        self.assertEqual((t["kind"], t["text"]), ("text", "print('hi')\n"))
        self.assertEqual(t["sha"], hashlib.sha256(b"print('hi')\n").hexdigest())
        b = self.r.read("p", "bin.dat")
        self.assertEqual((b["kind"], b["text"]), ("binary", None))

    def test_atomic_save_keeps_mode_and_detects_conflicts(self):
        t = self.r.read("p", "src/a.py")
        out = self.r.save("p", "src/a.py", "print('bye')\n", t["sha"])
        path = os.path.join(self.root, "src", "a.py")
        self.assertEqual(open(path).read(), "print('bye')\n")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o750)
        self.assertEqual(out["sha"], hashlib.sha256(b"print('bye')\n").hexdigest())
        # stale base: someone else changed it
        self.assertEqual(self.code(self.r.save, "p", "src/a.py", "x", t["sha"]), 409)
        self.assertEqual(open(path).read(), "print('bye')\n")
        # create-new refuses an existing name
        self.assertEqual(self.code(self.r.save, "p", "src/a.py", "x", None), 409)
        self.r.save("p", "src/new.txt", "n\n", None)
        self.assertEqual(open(os.path.join(self.root, "src", "new.txt")).read(), "n\n")
        self.assertFalse([n for n in os.listdir(os.path.join(self.root, "src")) if n.startswith(".ccd-")])

    def test_save_refuses_git_secrets_symlinks_binary_and_escape(self):
        sha = self.r.read("p", "bin.dat")["sha"]
        self.assertEqual(self.code(self.r.save, "p", "bin.dat", "x", sha), 400)
        self.assertEqual(self.code(self.r.save, "p", ".git/config", "x", None), 403)
        self.assertEqual(self.code(self.r.save, "p", ".env", "x", None), 403)
        self.assertEqual(self.code(self.r.save, "p", "../x.txt", "x", None), 400)
        self.assertEqual(self.code(self.r.save, "p", "escape", "x", None), 403)
        self.assertEqual(open(os.path.join(self.base, "outside.txt")).read(), "nope")

    def run_upload(self, *a, **kw):
        import asyncio

        async def gen(data):
            for i in range(0, len(data), 100):
                yield data[i:i + 100]
        data = kw.pop("data")
        return asyncio.run(self.r.upload(*a, gen(data), **kw))

    def test_upload_conflicts_never_overwrite_silently(self):
        out = self.run_upload("p", "src", "doc.pdf", data=b"one")
        self.assertEqual((out["name"], out["size"]), ("doc.pdf", 3))
        with self.assertRaises(FileError) as e:
            self.run_upload("p", "src", "doc.pdf", data=b"two")
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(open(os.path.join(self.root, "src", "doc.pdf"), "rb").read(), b"one")
        out = self.run_upload("p", "src", "doc.pdf", data=b"two", conflict="rename")
        self.assertEqual(out["name"], "doc (1).pdf")
        self.run_upload("p", "src", "doc.pdf", data=b"three", conflict="replace")
        self.assertEqual(open(os.path.join(self.root, "src", "doc.pdf"), "rb").read(), b"three")
        self.assertFalse([n for n in os.listdir(os.path.join(self.root, "src")) if n.startswith(".ccd-")])

    def test_upload_limits_and_forbidden_destinations(self):
        for args, status in ((("p", "src", "big.bin"), 413), (("p", ".git", "x"), 403), (("p", "src", ".env"), 403),
                             (("p", "src", "../x"), 400), (("p", "../", "x"), 400), (("p", "src", "a/b"), 400),
                             (("p", "src", "id_rsa"), 403), (("p", "escape", "x"), 403)):
            with self.assertRaises(FileError, msg=str(args)) as e:
                self.run_upload(*args, data=b"x" * (2048 if status == 413 else 1))
            self.assertEqual(e.exception.status, status, args)
        self.assertFalse([n for n in os.listdir(os.path.join(self.root, "src")) if n.startswith(".ccd-")])


class Developer(unittest.TestCase):
    def test_sessions_lockout_and_expiry(self):
        now = [1000.0]
        g = security.DeveloperGate(DEV_SECRET, clock=lambda: now[0])
        self.assertEqual(g.unlock("wrong")[0], None)
        sid, _ = g.unlock(DEV_SECRET)
        self.assertTrue(g.check(sid))
        self.assertFalse(g.check("x" + sid))
        now[0] += g.IDLE + 1
        self.assertFalse(g.check(sid))
        for _ in range(5):
            g.unlock("wrong")
        self.assertIn("too many", g.unlock(DEV_SECRET)[1])
        now[0] += g.FAIL_WINDOW + 1
        sid, _ = g.unlock(DEV_SECRET)
        g.lock(sid)
        self.assertFalse(g.check(sid))


class WorkspaceApi(ApiBase):
    def equip(self, daemon):
        self.base = tempfile.mkdtemp(prefix="wsapi-")
        self.root = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(self.root, "docs"))
        with open(os.path.join(self.root, "docs", "n.md"), "w") as f:
            f.write("# notes\n")
        daemon.files = Roots({"samvision": self.root}, upload_max=4096)
        daemon.attachments = attach_mod.Attachments(os.path.join(self.base, "att.db"),
                                                    os.path.join(self.base, "blobs"), 4096)
        daemon.dev_gate = security.DeveloperGate(DEV_SECRET)
        daemon.launcher_dir = os.path.join(self.base, "launcher")

    def tearDown(self):
        super().tearDown()
        self.daemon.attachments.close()
        shutil.rmtree(self.base)

    def unlock(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV_SECRET}), headers=JSON)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(DEV_SECRET, r.text)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def test_ordinary_token_reads_but_cannot_write(self):
        r = self.get("/api/files/read?project=samvision&path=docs/n.md")
        self.assertEqual(r.json()["text"], "# notes\n")
        body = json.dumps({"project": "samvision", "path": "docs/n.md", "text": "x", "baseSha": r.json()["sha"]})
        self.assertEqual(self.client.post("/api/files/save", content=body, headers=JSON).status_code, 403)
        bad = dict(JSON, **{"x-ccd-developer": TOKEN})  # the ccd token is not a developer session
        self.assertEqual(self.client.post("/api/files/save", content=body, headers=bad).status_code, 403)
        up = dict(AUTH, **{"content-type": "application/octet-stream"})
        self.assertEqual(self.client.post("/api/files/upload?project=samvision&dir=docs&name=a.txt", content=b"a",
                                          headers=up).status_code, 403)
        self.assertEqual(open(os.path.join(self.root, "docs", "n.md")).read(), "# notes\n")
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs", "a.txt")))

    def test_bad_developer_token_fails_and_good_one_saves(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": "nope"}), headers=JSON)
        self.assertEqual(r.status_code, 403)
        dev = self.unlock()
        self.assertTrue(self.client.get("/api/developer", headers=dev).json()["active"])
        sha = self.get("/api/files/read?project=samvision&path=docs/n.md").json()["sha"]
        body = json.dumps({"project": "samvision", "path": "docs/n.md", "text": "# new\n", "baseSha": sha})
        self.assertEqual(self.client.post("/api/files/save", content=body, headers=dev).status_code, 200)
        self.assertEqual(self.client.post("/api/files/save", content=body, headers=dev).status_code, 409)
        self.client.post("/api/developer/lock", content="{}", headers=dev)
        self.assertEqual(self.client.post("/api/files/save", content=body, headers=dev).status_code, 403)

    def test_upload_needs_octet_stream_and_unlock(self):
        dev = self.unlock()
        up = {k: v for k, v in dev.items() if k != "content-type"}
        up["content-type"] = "application/octet-stream"
        r = self.client.post("/api/files/upload?project=samvision&dir=docs&name=d.pdf", content=b"%PDF", headers=up)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/api/files/upload?project=samvision&dir=docs&name=d.pdf", content=b"x",
                                          headers=up).status_code, 409)
        self.assertEqual(self.client.post("/api/files/upload?project=samvision&dir=docs&name=big", content=b"x" * 5000,
                                          headers=up).status_code, 413)
        plain = dict(up, **{"content-type": "text/plain"})
        self.assertEqual(self.client.post("/api/files/upload?project=samvision&dir=docs&name=t", content=b"x",
                                          headers=plain).status_code, 415)
        # octet-stream is accepted on the two stream routes only
        self.assertEqual(self.client.post("/api/tasks", content=b"{}", headers=up).status_code, 415)

    def test_download_is_an_attachment(self):
        r = self.get("/api/files/download?project=samvision&path=docs/n.md")
        self.assertEqual(r.content, b"# notes\n")
        self.assertTrue(r.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(r.headers["content-type"], "application/octet-stream")
        self.assertEqual(self.get("/api/files/download?project=samvision&path=../x").status_code, 400)

    def test_attachments_round_trip_audited_and_outside_the_repo(self):
        t = self.client.post("/api/tasks", content=json.dumps({"project": "samvision", "title": "attach"}),
                             headers=JSON).json()
        dev = self.unlock()
        up = dict({k: v for k, v in dev.items() if k != "content-type"}, **{"content-type": "application/octet-stream"})
        name = "évil\"<script>.svg"
        r = self.client.post(f"/api/attachments?owner=ticket&key={t['key']}&name={name}", content=b"<svg/>",
                             headers=up)
        self.assertEqual(r.status_code, 200, r.text)
        row = r.json()
        self.assertRegex(row["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(row["name"], name)
        self.assertEqual(os.listdir(os.path.join(self.root, "docs")), ["n.md"])  # nothing entered the repo
        listed = self.get(f"/api/attachments?owner=ticket&key={t['key']}").json()["attachments"]
        self.assertEqual([a["id"] for a in listed], [row["id"]])
        d = self.get(f"/api/attachments/{row['id']}/download")
        self.assertEqual(d.content, b"<svg/>")
        self.assertEqual(d.headers["content-type"], "application/octet-stream")
        cd = d.headers["content-disposition"]
        self.assertTrue(cd.startswith("attachment; filename=\""))
        self.assertNotIn("<", cd.split("filename*=")[0])
        self.assertIn("sandbox", d.headers["content-security-policy"])
        # ordinary token cannot remove
        self.assertEqual(self.client.delete(f"/api/attachments/{row['id']}", headers=JSON).status_code, 403)
        self.assertEqual(self.client.request("DELETE", f"/api/attachments/{row['id']}", headers=dev,
                                             content="{}").status_code, 200)
        self.assertEqual(self.get(f"/api/attachments/{row['id']}/download").status_code, 404)
        kinds = [e["kind"] for e in self.get(f"/api/tasks/{t['key']}").json()["timeline"]]
        self.assertIn("attachment_added", kinds)
        self.assertIn("attachment_removed", kinds)
        timeline = json.dumps(self.get(f"/api/tasks/{t['key']}").json()["timeline"])
        self.assertNotIn("<svg/>", timeline)

    def test_attachment_owner_must_exist(self):
        dev = self.unlock()
        up = dict({k: v for k, v in dev.items() if k != "content-type"}, **{"content-type": "application/octet-stream"})
        self.assertEqual(self.client.post("/api/attachments?owner=ticket&key=SV-999&name=a", content=b"a",
                                          headers=up).status_code, 404)
        self.assertEqual(self.client.post("/api/attachments?owner=project&key=nope&name=a", content=b"a",
                                          headers=up).status_code, 404)
        self.assertEqual(self.client.post("/api/attachments?owner=project&key=samvision&name=a", content=b"a",
                                          headers=up).status_code, 200)

    def test_developer_token_never_leaves_or_logs(self):
        self.unlock()
        for path in ("/api/state", "/api/developer", "/api/activity?limit=100", "/api/workspace/projects"):
            self.assertNotIn(DEV_SECRET, self.get(path).text, path)

    def test_workspace_projects_come_from_the_registry(self):
        rows = self.get("/api/workspace/projects").json()["projects"]
        by = {r["key"]: r for r in rows}
        self.assertEqual(set(by), set(registry.PROJECTS))
        self.assertEqual(by["commandcenter"]["github"]["url"], "https://github.com/JayDalool/CommandCenter")
        self.assertEqual(by["samvision"]["root"], "/srv/server/apps/samvisionai")

    def test_state_pr_urls_are_canonical(self):
        st = self.get("/api/state").json()
        for p in st["projects"]:
            for pr in p["prs"]:
                self.assertTrue(pr["url"].startswith(f"https://github.com/{p['repo']}/pull/"), pr["url"])

    def test_launcher_absent_then_served_as_attachment(self):
        self.assertFalse(self.get("/api/desktop/launcher").json()["available"])
        os.makedirs(self.daemon.launcher_dir)
        with open(os.path.join(self.daemon.launcher_dir, "CommandCenter.exe"), "wb") as f:
            f.write(b"MZ..")
        with open(os.path.join(self.daemon.launcher_dir, "launcher.json"), "w") as f:
            json.dump({"version": "1", "sha256": "ab", "commit": "c", "built_at": "t", "size": 4, "extra": "no"}, f)
        info = self.get("/api/desktop/launcher").json()
        self.assertEqual((info["available"], info["sha256"]), (True, "ab"))
        self.assertNotIn("extra", info)
        d = self.get("/api/desktop/launcher/download")
        self.assertEqual(d.content, b"MZ..")
        self.assertIn('filename="CommandCenter.exe"', d.headers["content-disposition"])
        self.assertEqual(self.client.get("/api/desktop/launcher/download", headers=HOST).status_code, 401)


class DevCommits(unittest.TestCase):
    def test_git_log_range_links_and_bad_branches(self):
        import subprocess
        from ccd.daemon import Daemon
        root = tempfile.mkdtemp(prefix="gitrepo-")
        g = lambda *a: subprocess.run(["git", "-C", root, *a], check=True, capture_output=True)  # noqa: E731
        g("init", "-q", "-b", "main")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        g("checkout", "-q", "-b", "SV-056-x")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "SV-056: one")
        d = Daemon.__new__(Daemon)

        def plan(branch, base="main"):
            return {"out": {"key": "SV-056", "branch": branch, "base": base, "commits": [], "branchUrl": None},
                    "root": root, "slug": "JayDalool/SamVisionAI", "limit": 50}
        out = d.dev_commits_run(plan("SV-056-x"))
        self.assertEqual([c["message"] for c in out["commits"]], ["SV-056: one"])
        self.assertTrue(out["commits"][0]["url"].startswith("https://github.com/JayDalool/SamVisionAI/commit/"))
        self.assertEqual(d.dev_commits_run(plan("nope"))["error"], "branch not found locally")
        for bad in ("--output=/tmp/x", "a..b", None):
            self.assertEqual(d.dev_commits_run(plan(bad))["commits"], [])
        shutil.rmtree(root)


class Hardening(unittest.TestCase):
    def test_bidi_and_control_characters_dropped_from_attachment_names(self):
        self.assertEqual(attach_mod.display_name("invoice\u202efdp.exe"), "invoicefdp.exe")
        self.assertEqual(attach_mod.display_name("a\x07b\u200b.txt"), "ab.txt")
        self.assertEqual(attach_mod.display_name("C:\\Users\\jay\\notes.pdf"), "notes.pdf")

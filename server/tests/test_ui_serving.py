"""How ccd serves the built UI: cache policy, real 404s, release selection, and a production-build smoke.

The live bug this guards: a window still running an older build asked for /assets/monaco-<old>.js,
which an in-place rebuild had deleted -> "Failed to fetch dynamically imported module".
"""
import os
import re
import shutil
import tempfile
import unittest

from starlette.testclient import TestClient

from ccd import api

PORT = 7777
HOST = {"host": f"127.0.0.1:{PORT}"}
REPO_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "web", "app", "dist")


def serve(directory):
    return TestClient(api.UiFiles(directory, PORT), base_url=f"http://127.0.0.1:{PORT}")


class CachePolicy(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ui-")
        os.makedirs(os.path.join(self.dir, "assets"))
        with open(os.path.join(self.dir, "index.html"), "w") as f:
            f.write('<!doctype html><script type="module" src="/assets/index-AbCd1234.js"></script>')
        with open(os.path.join(self.dir, "assets", "index-AbCd1234.js"), "w") as f:
            f.write('import("./monaco-Zz9_Yy8-.js")')
        with open(os.path.join(self.dir, "assets", "monaco-Zz9_Yy8-.js"), "w") as f:
            f.write("export const monaco = 1;")
        self.c = serve(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_index_html_is_always_revalidated(self):
        for path in ("/", "/index.html"):
            r = self.c.get(path, headers=HOST)
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/html", r.headers["content-type"])
            self.assertEqual(r.headers["cache-control"], "no-cache")
            self.assertIn("default-src 'self'", r.headers["content-security-policy"])

    def test_hashed_assets_are_immutable_javascript(self):
        r = self.c.get("/assets/monaco-Zz9_Yy8-.js", headers=HOST)
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])
        self.assertEqual(r.headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")

    def test_a_missing_chunk_is_a_real_404_never_the_app_shell(self):
        for path in ("/assets/monaco-s93JKSES.js", "/assets/nope.css", "/missing.js"):
            r = self.c.get(path, headers=HOST)
            self.assertEqual(r.status_code, 404, path)
            self.assertNotIn("<!doctype html>", r.text.lower(), path)
            self.assertNotIn("text/html", r.headers.get("content-type", ""), path)
            self.assertEqual(r.headers["cache-control"], "no-store", path)

    def test_a_304_keeps_the_cache_policy(self):
        r = self.c.get("/assets/monaco-Zz9_Yy8-.js", headers=HOST)
        r2 = self.c.get("/assets/monaco-Zz9_Yy8-.js", headers=dict(HOST, **{"if-none-match": r.headers["etag"]}))
        self.assertEqual(r2.status_code, 304)
        self.assertEqual(r2.headers["cache-control"], "public, max-age=31536000, immutable")
        i = self.c.get("/", headers=HOST)
        i2 = self.c.get("/", headers=dict(HOST, **{"if-none-match": i.headers["etag"]}))
        self.assertEqual(i2.status_code, 304)
        self.assertEqual(i2.headers["cache-control"], "no-cache")

    def test_unhashed_files_are_revalidated(self):
        with open(os.path.join(self.dir, "favicon.svg"), "w") as f:
            f.write("<svg/>")
        self.assertEqual(self.c.get("/favicon.svg", headers=HOST).headers["cache-control"], "no-cache")


class ReleaseSelection(unittest.TestCase):
    def setUp(self):
        self.share = tempfile.mkdtemp(prefix="share-")
        self.env = {k: os.environ.get(k) for k in ("CCD_UI_DIR", "CCD_SHARE_DIR")}
        os.environ.pop("CCD_UI_DIR", None)
        os.environ["CCD_SHARE_DIR"] = self.share

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.share)

    def test_current_release_wins_and_switching_needs_no_restart(self):
        self.assertTrue(str(api.ui_dir()).endswith(os.path.join("web", "app", "dist")))  # no release yet
        web = os.path.join(self.share, "web")
        for name, body in (("r1", "one"), ("r2", "two")):
            os.makedirs(os.path.join(web, "releases", name, "assets"))
            with open(os.path.join(web, "releases", name, "index.html"), "w") as f:
                f.write(body)
        os.symlink("releases/r1", os.path.join(web, "current"))
        self.assertEqual(str(api.ui_dir()), os.path.join(web, "current"))
        c = serve(api.ui_dir())
        self.assertEqual(c.get("/index.html", headers=HOST).text, "one")
        os.symlink("releases/r2", os.path.join(web, "current.next"))
        os.replace(os.path.join(web, "current.next"), os.path.join(web, "current"))  # the deploy's atomic switch
        self.assertEqual(c.get("/index.html", headers=HOST).text, "two")  # same server object, new release


@unittest.skipUnless(os.path.isfile(os.path.join(REPO_DIST, "index.html")), "needs a production build (npm run build)")
class ProductionBuildSmoke(unittest.TestCase):
    """The real build, served by the real UiFiles: the editor's lazy chunk loads as JavaScript."""

    def test_every_lazy_chunk_the_main_bundle_imports_is_served_as_javascript(self):
        c = serve(REPO_DIST)
        html = c.get("/", headers=HOST).text
        main = re.search(r'src="(/assets/index-[^"]+\.js)"', html).group(1)
        r = c.get(main, headers=HOST)
        self.assertEqual(r.status_code, 200)
        chunks = set(re.findall(r'(?:\./|/assets/)([A-Za-z0-9._-]+-[A-Za-z0-9_-]{8}\.js)', r.text))
        self.assertTrue(any(n.startswith("monaco-") for n in chunks), "the editor chunk is lazily imported by name")
        self.assertTrue(any(n.startswith("xterm-") for n in chunks), "the terminal chunk is lazily imported by name")
        for name in chunks:
            rr = c.get(f"/assets/{name}", headers=HOST)
            self.assertEqual(rr.status_code, 200, name)
            self.assertIn("javascript", rr.headers["content-type"], name)
            self.assertEqual(rr.headers["cache-control"], "public, max-age=31536000, immutable", name)
        monaco = next(n for n in chunks if n.startswith("monaco-"))
        deps = set(re.findall(r'(?:\./|/assets/)([A-Za-z0-9._-]+-[A-Za-z0-9_-]{8}\.(?:js|css))', c.get(f"/assets/{monaco}", headers=HOST).text))
        for d in deps:  # Monaco's own dependencies (editor core, workers, css) are there too
            self.assertEqual(c.get(f"/assets/{d}", headers=HOST).status_code, 200, d)

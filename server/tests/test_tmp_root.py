"""The test run's temp files stay under one root that is removed at exit (tests/__init__.py)."""
import os
import tempfile
import unittest

from tests import _TMP


class TmpRootTest(unittest.TestCase):
    def test_temp_files_land_under_the_run_root(self):
        self.assertEqual(tempfile.gettempdir(), _TMP)
        self.assertEqual(os.environ["TMPDIR"], _TMP)
        d = tempfile.mkdtemp(prefix="ccd-db-")
        self.assertEqual(os.path.dirname(d), _TMP)
        self.assertTrue(os.path.basename(_TMP).startswith("ccd-tests-"))


if __name__ == "__main__":
    unittest.main()

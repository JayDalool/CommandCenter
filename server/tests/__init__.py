"""Test package. Points ccd at throwaway directories before any ccd module loads."""
import atexit
import os
import shutil
import tempfile

# One temp root per test run. Every mkdtemp/mkstemp/TemporaryDirectory in the tests (and TMPDIR for the
# processes they start) lands under it, and it is removed when the run exits, so /tmp does not fill up.
_TMP = tempfile.mkdtemp(prefix="ccd-tests-")
tempfile.tempdir = _TMP
os.environ["TMPDIR"] = _TMP
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ["CCD_STATE_DIR"] = os.path.join(_TMP, "state")
os.environ["CCD_HANDOFF"] = os.path.join(_TMP, "handoff")
os.environ["CCD_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["CCD_TOKEN_FILE"] = os.path.join(_TMP, "token")
os.environ["CCD_CONFIG"] = os.path.join(_TMP, "no-config.json")  # never read the real one (ntfy URL)
os.makedirs(os.environ["CCD_STATE_DIR"], exist_ok=True)
os.makedirs(os.environ["CCD_HANDOFF"], exist_ok=True)

import logging  # noqa: E402

logging.getLogger("ccd").addHandler(logging.NullHandler())
logging.getLogger("ccd").propagate = False

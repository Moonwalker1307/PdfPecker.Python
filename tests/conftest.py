import os
import sys

# Tests run against the installed wheel in CI; from a checkout with the native library copied into src/pdfpecker,
# they run against the source tree.
if os.environ.get("PDFPECKER_TEST_INSTALLED") != "1":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

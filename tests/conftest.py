import os
import sys
import tempfile

# All tests use a throw-away database so the project's real data/ folder is never touched.
os.environ["ATTENDANCE_DB"] = os.path.join(tempfile.mkdtemp(prefix="attendance_test_"), "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

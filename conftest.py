"""Make the ``src`` layout importable when running tests without installation."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

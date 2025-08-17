import os
import sys

# Ensure project root is importable
BASE_DIR = os.path.dirname(__file__)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app

# WSGI callable expected by mod_wsgi
app = create_app()
application = app

"""Root conftest — sets environment variables before any Caldanai modules are imported."""

import os

os.environ.setdefault("DB_CONNECTION", "mongodb://localhost:27017")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("STAGE", "TEST")

"""KnowTwin test configuration."""
import os

TEST_DB_HOST = os.environ.get("TEST_DB_HOST", "localhost")
TEST_DB_PORT = os.environ.get("TEST_DB_PORT", "5436")
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "knowtwin")
TEST_DB_USER = os.environ.get("TEST_DB_USER", "knowtwin")
TEST_DB_PASS = os.environ.get("TEST_DB_PASS", "knowtwin_test_pass")

TEST_DB_URL = f"postgresql://{TEST_DB_USER}:{TEST_DB_PASS}@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}"

TEST_API_URL = os.environ.get("TEST_API_URL", "http://localhost:8090")

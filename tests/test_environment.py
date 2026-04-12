"""Tests for Caldanai.environment."""

import importlib
from unittest.mock import patch


class TestEnvironment:
    def test_missing_db_connection_raises_runtime_error(self):
        """DB_CONNECTION unset should raise RuntimeError."""
        with patch.dict("os.environ", {"LOG_LEVEL": "INFO", "STAGE": "PROD"}, clear=True):
            with patch("dotenv.load_dotenv"):
                import caldanai.environment as env_mod
                import pytest
                with pytest.raises(RuntimeError, match="DB_CONNECTION"):
                    importlib.reload(env_mod)

    def test_defaults_for_log_level_and_stage(self):
        """LOG_LEVEL and STAGE should get defaults when not set."""
        with patch.dict("os.environ", {"DB_CONNECTION": "mongodb://localhost:27017"}, clear=True):
            with patch("dotenv.load_dotenv"):
                import caldanai.environment as env_mod
                importlib.reload(env_mod)
                assert env_mod.LOG_LEVEL == "INFO"
                assert env_mod.STAGE == "PROD"

    def test_custom_values_are_used(self):
        """Explicit env values should be picked up."""
        with patch.dict(
            "os.environ",
            {"DB_CONNECTION": "mongodb://custom:1234", "LOG_LEVEL": "WARNING", "STAGE": "TEST"},
            clear=True,
        ):
            with patch("dotenv.load_dotenv"):
                import caldanai.environment as env_mod
                importlib.reload(env_mod)
                assert env_mod.DB_CONNECTION == "mongodb://custom:1234"
                assert env_mod.LOG_LEVEL == "WARNING"
                assert env_mod.STAGE == "TEST"

"""Tests for Caldanai.db (DB class)."""

import importlib
from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest
from pymongo import DeleteMany, DeleteOne, InsertOne, UpdateOne

from caldanai.double_buffer import DoubleBuffer


# ---------------------------------------------------------------------------
# We must patch MongoClient BEFORE the DB class body executes, because
# ``_mongoClient = MongoClient(DB_CONNECTION)`` runs at class-definition time.
# Using importlib.reload inside a fixture that already holds the patch ensures
# the patched MongoClient is used for the class-level assignment.
# ---------------------------------------------------------------------------

_mock_client = MagicMock()
_mock_db_obj = MagicMock()
_mock_client.caldanaiTest = _mock_db_obj
_mock_client.caldanaiDB = _mock_db_obj
_mock_client.admin.command = MagicMock(return_value={"ok": 1})


@pytest.fixture(autouse=True)
def _patch_mongo():
    """Patch MongoClient so DB class never connects to a real database."""
    with patch("pymongo.MongoClient", return_value=_mock_client) as patched:
        import caldanai.db as db_mod
        importlib.reload(db_mod)
        yield _mock_client
        # Reload again on teardown so the module is in a clean state for
        # non-db tests that might import it.


@pytest.fixture
def fresh_db(_patch_mongo):
    """Return the DB class with reset queues."""
    import caldanai.db as db_mod
    DB = db_mod.DB

    # Reset state
    DB._queues = defaultdict(DoubleBuffer)
    DB._is_connected = False
    DB._write_alert_sent = False
    DB._last_successful_write = None
    return DB


class TestConnectionState:
    def test_on_connected_sets_flag(self, fresh_db):
        DB = fresh_db
        DB._is_connected = False
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = True
        DB.batch_write = MagicMock()
        DB.batch_write.is_running.return_value = False

        DB.on_connected()

        assert DB._is_connected is True
        assert DB._write_alert_sent is False
        DB.poll_for_connection.stop.assert_called_once()
        DB.batch_write.start.assert_called_once()

    def test_on_connected_does_not_stop_poll_if_not_running(self, fresh_db):
        DB = fresh_db
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False
        DB.batch_write = MagicMock()
        DB.batch_write.is_running.return_value = True

        DB.on_connected()

        DB.poll_for_connection.stop.assert_not_called()
        DB.batch_write.start.assert_not_called()

    def test_on_disconnected_sets_flag(self, fresh_db):
        DB = fresh_db
        DB._is_connected = True
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False

        DB.on_disconnected()

        assert DB._is_connected is False
        DB.poll_for_connection.start.assert_called_once()

    def test_on_disconnected_does_not_start_poll_if_running(self, fresh_db):
        DB = fresh_db
        DB._is_connected = True
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = True

        DB.on_disconnected()

        DB.poll_for_connection.start.assert_not_called()


class TestQueueOperations:
    def test_update_player_enqueues_update_one(self, fresh_db):
        DB = fresh_db
        DB.update_player(guild_id=1, user_id=2, player_dict={"name": "test"})
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)

    def test_delete_player_enqueues_delete_one(self, fresh_db):
        DB = fresh_db
        DB.delete_player(guild_id=1, user_id=2)
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], DeleteOne)

    def test_delete_all_players_enqueues_delete_many(self, fresh_db):
        DB = fresh_db
        DB.delete_all_players(guild_id=1)
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], DeleteMany)

    def test_insert_server_enqueues_insert_one(self, fresh_db):
        DB = fresh_db
        DB.insert_server(guild_id=1, name="Test", prefix="!")
        ops = list(DB._queues[DB._servers].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], InsertOne)

    def test_delete_server_enqueues_across_collections(self, fresh_db):
        DB = fresh_db
        DB.delete_server(guild_id=1)
        server_ops = list(DB._queues[DB._servers].get_all())
        game_ops = list(DB._queues[DB._games].get_all())
        player_ops = list(DB._queues[DB._players].get_all())
        assert len(server_ops) == 1
        assert isinstance(server_ops[0], DeleteOne)
        assert len(game_ops) == 1
        assert isinstance(game_ops[0], DeleteMany)
        assert len(player_ops) == 1
        assert isinstance(player_ops[0], DeleteMany)

    def test_delete_game_enqueues_game_and_players(self, fresh_db):
        DB = fresh_db
        DB.delete_game(guild_id=1)
        game_ops = list(DB._queues[DB._games].get_all())
        player_ops = list(DB._queues[DB._players].get_all())
        assert len(game_ops) == 1
        assert isinstance(game_ops[0], DeleteOne)
        assert len(player_ops) == 1
        assert isinstance(player_ops[0], DeleteMany)

    def test_update_game_enqueues_update_one(self, fresh_db):
        DB = fresh_db
        DB.update_game(guild_id=1, guild_dict={"status": "active"}, upsert=True)
        ops = list(DB._queues[DB._games].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)

    def test_insert_game_enqueues_insert_one(self, fresh_db):
        DB = fresh_db
        DB.insert_game(guild_id=1, channel_id=999)
        ops = list(DB._queues[DB._games].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], InsertOne)

    def test_update_statistic_enqueues_update_one(self, fresh_db):
        DB = fresh_db
        DB.update_statistic(guild_id=1, inc_doc={"commands": 1})
        ops = list(DB._queues[DB._statics].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)

    def test_update_user_statics_enqueues_insert_one(self, fresh_db):
        DB = fresh_db
        DB.update_user_statics({"user_id": 1, "command": "help"})
        ops = list(DB._queues[DB._command_statics].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], InsertOne)

    def test_update_server_prefix_enqueues_update_one(self, fresh_db):
        DB = fresh_db
        DB.update_server_prefix(guild_id=1, prefix="!")
        ops = list(DB._queues[DB._servers].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)


class TestCheckConnectionDecorator:
    def test_check_connection_success_calls_function(self, fresh_db):
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False
        DB.batch_write = MagicMock()
        DB.batch_write.is_running.return_value = True

        @DB.check_connection
        def my_func():
            return "result"

        assert my_func() == "result"

    def test_check_connection_failure_calls_on_disconnected(self, fresh_db):
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.side_effect = Exception("connection failed")
        DB._is_connected = True
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False

        @DB.check_connection
        def my_func():
            return "should not reach"

        result = my_func()
        assert result is None
        assert DB._is_connected is False

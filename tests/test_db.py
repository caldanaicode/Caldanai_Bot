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
# DB selection is now ``_mongoClient[name]`` rather than
# ``_mongoClient.attr``, so the mock needs to handle subscript
# access regardless of which DB name the env-driven config
# resolves to in the test environment.
_mock_client.__getitem__ = MagicMock(return_value=_mock_db_obj)
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
        """2026-04-21 loop-collapse: ``on_connected`` no longer starts
        ``batch_write`` (the task loop is gone — ``save_game_data`` is
        the single DB-write-pipeline driver now and its start is owned
        by ``RpgUtilities.initialize``, not the DB connection hook)."""
        DB = fresh_db
        DB._is_connected = False
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = True

        DB.on_connected()

        assert DB._is_connected is True
        assert DB._write_alert_sent is False
        DB.poll_for_connection.stop.assert_called_once()

    def test_on_connected_does_not_stop_poll_if_not_running(self, fresh_db):
        DB = fresh_db
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False

        DB.on_connected()

        DB.poll_for_connection.stop.assert_not_called()

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
        DB.update_player(guild_id=1, channel_id=888, user_id=2, player_dict={"name": "test"})
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)
        assert ops[0]._filter == {"guild_id": 1, "channel_id": 888, "user_id": 2}

    def test_delete_player_enqueues_delete_one(self, fresh_db):
        DB = fresh_db
        DB.delete_player(guild_id=1, channel_id=888, user_id=2)
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], DeleteOne)
        assert ops[0]._filter == {"guild_id": 1, "channel_id": 888, "user_id": 2}

    def test_delete_all_players_enqueues_delete_many(self, fresh_db):
        DB = fresh_db
        DB.delete_all_players(guild_id=1)
        ops = list(DB._queues[DB._players].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], DeleteMany)

    def test_insert_server_enqueues_idempotent_upsert(self, fresh_db):
        """Server inserts are idempotent: an UpdateOne with upsert=True
        and ``$setOnInsert`` so repeated calls produce exactly one row
        per guild_id and don't overwrite an existing prefix."""
        DB = fresh_db
        DB.insert_server(guild_id=1, name="Test", prefix="!")
        ops = list(DB._queues[DB._servers].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)
        # Filter is by guild_id; update uses $setOnInsert so the
        # prefix is only written for new rows.
        assert ops[0]._filter == {"guild_id": 1}

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
        DB.delete_game(guild_id=1, channel_id=999)
        game_ops = list(DB._queues[DB._games].get_all())
        player_ops = list(DB._queues[DB._players].get_all())
        assert len(game_ops) == 1
        assert isinstance(game_ops[0], DeleteOne)
        # Query filter carries both ids so only the specific game is
        # dropped, not every game in the guild.
        assert game_ops[0]._filter == {"guild_id": 1, "channel_id": 999}
        assert len(player_ops) == 1
        assert isinstance(player_ops[0], DeleteMany)
        # Player deletion is now game-scoped too.
        assert player_ops[0]._filter == {"guild_id": 1, "channel_id": 999}

    def test_update_game_enqueues_update_one(self, fresh_db):
        DB = fresh_db
        DB.update_game(
            guild_id=1, channel_id=999,
            guild_dict={"status": "active"}, upsert=True,
        )
        ops = list(DB._queues[DB._games].get_all())
        assert len(ops) == 1
        assert isinstance(ops[0], UpdateOne)
        assert ops[0]._filter == {"guild_id": 1, "channel_id": 999}

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


class TestGuildChannels:
    """``set_guild_channel`` / ``get_guild_channels`` manage the
    per-guild named-channel registry stored under ``channels`` on
    the server document. Used by tooling (updates posting,
    ideas channel reading) to look up where to write/read without
    hardcoding channel ids."""

    def test_set_guild_channel_enqueues_upsert(self, fresh_db):
        DB = fresh_db
        DB.set_guild_channel(guild_id=1, key="updates", channel_id=42)
        ops = list(DB._queues[DB._servers].get_all())
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, UpdateOne)
        # Upsert so a guild without a server document yet still
        # gets one created with the channel registered.
        assert op._doc == {"$set": {"channels.updates": 42}}
        assert op._filter == {"guild_id": 1}
        assert op._upsert is True

    def test_set_guild_channel_rejects_unknown_key(self, fresh_db):
        """A typo at the call site should raise rather than write a
        garbage field that nothing reads."""
        DB = fresh_db
        with pytest.raises(ValueError, match="Unknown guild channel key"):
            DB.set_guild_channel(guild_id=1, key="updaates", channel_id=42)
        # No write enqueued from a rejected call.
        assert DB._queues[DB._servers].get_all() == []

    def test_set_guild_channel_accepts_every_registered_key(self, fresh_db):
        """Every key in ``GUILD_CHANNEL_KEYS`` must be writable.
        Catches a constant/setter mismatch."""
        DB = fresh_db
        for key in DB.GUILD_CHANNEL_KEYS:
            DB.set_guild_channel(guild_id=1, key=key, channel_id=99)
        ops = list(DB._queues[DB._servers].get_all())
        assert len(ops) == len(DB.GUILD_CHANNEL_KEYS)

    def _wire_get_helpers(self, DB):
        """Pre-arrange the mocks the ``@check_connection`` decorator
        depends on so a sync test can call a wrapped DB getter
        without spinning up an event loop for the drain-queue
        scheduler."""
        DB._is_connected = True
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}

    def test_get_guild_channels_returns_dict(self, fresh_db):
        DB = fresh_db
        self._wire_get_helpers(DB)
        DB._mongoDB = MagicMock()
        DB._mongoDB.servers.find_one.return_value = {
            "guild_id": 1,
            "channels": {"updates": 100, "ideas": 200},
        }
        channels = DB.get_guild_channels(guild_id=1)
        assert channels == {"updates": 100, "ideas": 200}

    def test_get_guild_channels_empty_when_no_server_doc(self, fresh_db):
        """Callers should be able to ``.get(key)`` on the result
        without pre-checking. Missing server doc → empty dict, not
        None."""
        DB = fresh_db
        self._wire_get_helpers(DB)
        DB._mongoDB = MagicMock()
        DB._mongoDB.servers.find_one.return_value = None
        assert DB.get_guild_channels(guild_id=1) == {}

    def test_get_guild_channels_empty_when_no_channels_field(self, fresh_db):
        """Server doc exists but no ``channels`` field yet (older
        document). Same empty-dict semantics."""
        DB = fresh_db
        self._wire_get_helpers(DB)
        DB._mongoDB = MagicMock()
        DB._mongoDB.servers.find_one.return_value = {"guild_id": 1, "prefix": "$"}
        assert DB.get_guild_channels(guild_id=1) == {}


class TestCheckConnectionDecorator:
    def test_check_connection_success_calls_function(self, fresh_db):
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}
        DB.poll_for_connection = MagicMock()
        DB.poll_for_connection.is_running.return_value = False

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


class TestFlushAll:
    """``DB.flush_all`` is the synchronous drain called during
    shutdown. Must: (1) drain every collection queue that has
    pending ops, (2) pass those ops to ``collection.bulk_write``,
    (3) swallow ``BulkWriteError`` so one failing collection doesn't
    prevent the others from flushing."""

    def test_drains_every_collection_with_pending_ops(self, fresh_db):
        DB = fresh_db
        games = MagicMock()
        games.full_name = "db.games"
        players = MagicMock()
        players.full_name = "db.players"
        DB._queues[games].put(UpdateOne({"_id": 1}, {"$set": {"x": 1}}))
        DB._queues[games].put(UpdateOne({"_id": 2}, {"$set": {"x": 2}}))
        DB._queues[players].put(InsertOne({"_id": 3}))

        DB.flush_all()

        games.bulk_write.assert_called_once()
        games_ops = games.bulk_write.call_args.args[0]
        assert len(games_ops) == 2
        assert games.bulk_write.call_args.kwargs == {"ordered": False}

        players.bulk_write.assert_called_once()
        players_ops = players.bulk_write.call_args.args[0]
        assert len(players_ops) == 1

        # Queues are drained after flush — re-flushing is a no-op.
        assert DB._queues[games].get_all() == []
        assert DB._queues[players].get_all() == []

    def test_skips_empty_collections(self, fresh_db):
        """A collection with no queued ops should not trigger a
        ``bulk_write`` call — pymongo errors on empty op lists."""
        DB = fresh_db
        games = MagicMock()
        games.full_name = "db.games"
        DB._queues[games]  # touch to create the empty queue

        DB.flush_all()

        games.bulk_write.assert_not_called()

    def test_continues_past_collection_with_bulk_write_error(self, fresh_db):
        """A failing bulk_write on one collection must not abort the
        rest of the flush — each remaining collection still gets
        attempted. Protects against a schema issue on one queue
        eating every pending write across the system."""
        from pymongo.errors import BulkWriteError
        DB = fresh_db
        bad = MagicMock()
        bad.full_name = "db.bad"
        bad.bulk_write.side_effect = BulkWriteError({"errmsg": "boom"})
        good = MagicMock()
        good.full_name = "db.good"
        DB._queues[bad].put(UpdateOne({"_id": 1}, {"$set": {"x": 1}}))
        DB._queues[good].put(InsertOne({"_id": 2}))

        DB.flush_all()

        bad.bulk_write.assert_called_once()
        good.bulk_write.assert_called_once()

    def test_drains_mongo_log_handler_queue(self, fresh_db):
        """The Mongo log handler has its own queue that
        ``drain_queues_once`` drains into ``DB._logs``. ``flush_all``
        must mirror that — otherwise in-flight log lines die on
        shutdown."""
        DB = fresh_db
        DB._logs = MagicMock()
        DB._logs.full_name = "db.logs"
        DB._mongoHandler = MagicMock()
        DB._mongoHandler.queue.get_all.return_value = [
            {"msg": "line1"}, {"msg": "line2"},
        ]

        DB.flush_all()

        DB._logs.bulk_write.assert_called_once()
        log_ops = DB._logs.bulk_write.call_args.args[0]
        assert len(log_ops) == 2
        assert all(isinstance(op, InsertOne) for op in log_ops)

    def test_no_mongo_handler_is_fine(self, fresh_db):
        """Early startup / test runs don't have a Mongo log handler
        — ``flush_all`` must not crash when ``DB._mongoHandler`` is
        ``None``."""
        DB = fresh_db
        DB._mongoHandler = None
        # Should not raise.
        DB.flush_all()


class TestDrainQueuesOnceRetry:
    """``DB.drain_queues_once`` pushes batches that failed with a
    transient connection error onto each DoubleBuffer's ``retry``
    sub-queue, then drains the retry queue ahead of fresh ops on
    the next cycle. Pins: (1) transient-error re-queue, (2) retry
    drain priority on recovery, (3) BulkWriteError ops are NOT
    re-queued (data errors don't heal on retry)."""

    @pytest.mark.asyncio
    async def test_transient_error_requeues_ops_to_retry_buffer(self, fresh_db):
        from pymongo.errors import AutoReconnect
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}
        DB._is_connected = True

        collection = MagicMock()
        collection.full_name = "db.games"
        collection.bulk_write.side_effect = AutoReconnect("connection dropped")
        op1 = UpdateOne({"_id": 1}, {"$set": {"x": 1}})
        op2 = UpdateOne({"_id": 2}, {"$set": {"x": 2}})
        DB._queues[collection].put(op1)
        DB._queues[collection].put(op2)

        await DB.drain_queues_once()

        # Fresh queues drained, ops sitting in the retry holding pen.
        buf = DB._queues[collection]
        assert buf.get_all() == []
        retry_ops = []
        while not buf.retry.empty():
            retry_ops.append(buf.retry.get_nowait())
        assert len(retry_ops) == 2
        # Connection flag flipped so the next caller knows to reconnect.
        assert DB._is_connected is False

    @pytest.mark.asyncio
    async def test_retry_ops_drained_ahead_of_fresh_on_recovery(self, fresh_db):
        """Once Mongo comes back, the next drain merges retry + fresh
        into one bulk_write with retry ops first (they've been waiting
        longer)."""
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}
        DB._is_connected = True

        collection = MagicMock()
        collection.full_name = "db.games"
        retry_op = UpdateOne({"_id": 1}, {"$set": {"x": 1}})
        fresh_op = UpdateOne({"_id": 2}, {"$set": {"x": 2}})
        buf = DB._queues[collection]
        buf.retry.put(retry_op)
        buf.put(fresh_op)

        await DB.drain_queues_once()

        collection.bulk_write.assert_called_once()
        sent_ops = collection.bulk_write.call_args.args[0]
        assert sent_ops == [retry_op, fresh_op]
        # Retry sub-queue is drained too.
        assert buf.retry.empty()

    @pytest.mark.asyncio
    async def test_bulk_write_error_does_not_requeue(self, fresh_db):
        """Data-shape errors (schema violation, duplicate key, etc.)
        won't heal on retry — requeuing would create an infinite
        loop. The batch must be logged and dropped."""
        from pymongo.errors import BulkWriteError
        DB = fresh_db
        DB._mongoClient = MagicMock()
        DB._mongoClient.admin.command.return_value = {"ok": 1}
        DB._is_connected = True

        collection = MagicMock()
        collection.full_name = "db.games"
        collection.bulk_write.side_effect = BulkWriteError(
            {"errmsg": "schema", "nInserted": 0, "nModified": 0}
        )
        DB._queues[collection].put(UpdateOne({"_id": 1}, {"$set": {"x": 1}}))

        await DB.drain_queues_once()

        assert DB._queues[collection].retry.empty()

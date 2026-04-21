"""Console command for inspecting DB worker health.

Reports:
- Whether the DB's ``batch_write`` tick is running.
- Whether the DB's ``watchdog`` tick is running (the supervisor that
  restarts downed loops).
- Whether ``save_game_data`` is running (the per-minute loop that
  enqueues player / game writes).
- Timestamp of the last successful write (and how stale it is).
- Pending write depth per Mongo collection.

Useful when players report "my progress isn't saving" — in a single
command you can confirm whether the pipeline is alive, where the
backlog is, and whether the last write succeeded.
"""

from datetime import datetime
from typing import Any, List

from caldanai.console_commands import CommandPlugin
from caldanai.db import DB
from caldanai.lib.bot.bot_state import BotState
from caldanai.logger import stdout


class DbStatusCommand(CommandPlugin):
    """
    Reports on the health of the DB write pipeline.

    Usage:
        `db_status`

    Example:
        `db_status`
    """

    COMMAND = "db_status"
    ALIASES = ["dbstatus", "db"]

    @staticmethod
    async def execute(args: List[Any], state: BotState):
        lines = ["DB pipeline status:"]

        # Task loop liveness. ``is_running`` returns False if the
        # task crashed or was stopped; watchdog restarts it within
        # 5 minutes if it's supposed to be running.
        #
        # ``save_game_data`` (rpg/helpers/utils.py) is the single
        # DB-write-pipeline driver post-2026-04-21 loop collapse —
        # it calls save_all_now() to populate queues and then
        # DB.drain_queues_once() to flush, both in the same 1-minute
        # tick. No separate ``batch_write`` loop anymore.
        watchdog_running = DB.watchdog.is_running()
        lines.append(f"  watchdog:        {'running' if watchdog_running else 'STOPPED'}")

        try:
            from caldanai.lib.rpg.helpers.utils import save_game_data
            sgd_running = save_game_data.is_running()
        except Exception:
            sgd_running = None
        lines.append(
            f"  save_game_data:  {'running' if sgd_running else 'STOPPED' if sgd_running is False else 'unknown'}"
        )

        # Last successful write — how stale is the pipeline?
        last = getattr(DB, "_last_successful_write", None)
        if last is None:
            lines.append("  last write:      never")
        else:
            age = datetime.now() - last
            total_seconds = int(age.total_seconds())
            if total_seconds < 60:
                age_str = f"{total_seconds}s ago"
            elif total_seconds < 3600:
                age_str = f"{total_seconds // 60}m ago"
            else:
                age_str = f"{total_seconds // 3600}h {(total_seconds % 3600) // 60}m ago"
            # Warn visibly if stale beyond what the watchdog tolerates.
            stale_flag = "  (STALE)" if total_seconds > 600 else ""
            lines.append(
                f"  last write:      {last.isoformat(timespec='seconds')}  ({age_str}){stale_flag}"
            )

        # Queue depths — anything built up here is waiting to be
        # written. Non-zero at inspection-time is fine if a batch
        # just came in; persistent high depth means batch_write
        # can't keep up or has stopped.
        lines.append("  pending writes:")
        if getattr(DB, "_queues", None):
            for collection, buf in DB._queues.items():
                # Buffer has active + passive queues; count both.
                pending = buf.active.qsize() + buf.passive.qsize()
                retry = getattr(buf, "retry", None)
                retry_depth = retry.qsize() if retry is not None else 0
                line = f"    {collection.name:20} pending={pending}"
                if retry_depth:
                    line += f"  retry={retry_depth}"
                lines.append(line)
        else:
            lines.append("    (queues not initialized)")

        stdout("\n".join(lines))

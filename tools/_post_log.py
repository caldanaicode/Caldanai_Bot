"""Persistence for the per-guild "last posted" record used by
:mod:`tools.post_patch_notes` and :mod:`tools.edit_patch_notes`.

Each successful post by ``post_patch_notes`` writes an entry
``{guild_id: {channel_id, message_id, posted_at}}`` into a
per-env file (``tools/.last_posted.<db_env_var>.json``).
``edit_patch_notes`` reads from the file matching the env-var
name passed at invocation — no channel scanning, no
``GET /users/@me``, scope naturally limited to messages we
actually posted via the tool against the same database.

The file storage lives on the shared ``state_file_*`` helpers
in :mod:`tools._common`; this module is a thin domain wrapper
that exposes the post-tracking shape (``record_post`` etc.)
rather than the generic JSON-state shape.
"""

from datetime import datetime, timezone

from tools._common import load_state_file, save_state_file


_BASE = "last_posted"


def record_post(
    db_env_var: str, guild_id: int, channel_id: int, message_id: int,
) -> None:
    """Record a successful post. Overwrites any prior entry for
    the same (db_env_var, guild_id) pair — only the most recent
    post is editable via the default edit-tool path."""
    data = load_state_file(_BASE, db_env_var)
    data[str(guild_id)] = {
        "channel_id": int(channel_id),
        "message_id": int(message_id),
        "posted_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state_file(_BASE, db_env_var, data)


def get_last_posted(db_env_var: str, guild_id: int) -> dict | None:
    """Return the last-posted record for ``(db_env_var, guild_id)``,
    or ``None`` when nothing has been posted from this machine
    via that env var for that guild."""
    return load_state_file(_BASE, db_env_var).get(str(guild_id))


def get_all_last_posted(db_env_var: str) -> dict:
    """Return the full file contents for ``db_env_var`` — used
    by the edit tool to iterate every guild that has a recorded
    post on the matching database."""
    return load_state_file(_BASE, db_env_var)

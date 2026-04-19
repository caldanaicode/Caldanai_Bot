# tools/

Standalone Python scripts that interact with the live Discord
guild **as the bot** for operator workflows that don't make
sense as game commands. Designed to live alongside the bot's
codebase but run independently — no Gateway connection, REST
calls only, so they coexist with the live bot without conflict.

## Setup

The tools share the project's `.env` and Mongo connection. The
operator picks **per invocation** which database to talk to by
passing the env-var *name* that holds the desired DB name as
the first positional argument. Default is `LIVE_DB_NAME` (so
unadorned invocations target production).

```
DB_CONNECTION=mongodb+srv://...           # cluster URI; same as the bot
LIVE_DB_NAME=your_live_db_name            # production DB
TEST_DB_NAME=your_test_db_name            # local/test DB (only needed if you'll
                                          # invoke tools against it)
```

Both `LIVE_DB_NAME` and `TEST_DB_NAME` have generic defaults if
unset, but for any real deployment / local-dev setup the actual
names will differ — set them explicitly.

The bot token is pulled from the `auth` document on whichever
database the operator selected; no separate token env var is
needed.

## Per-guild registration

Each tool needs to know which Discord channel to read from or
post to. That's stored on the `servers` Mongo collection per
guild and configured **from inside Discord** by the guild owner
(or anyone with Manage Server):

```
$config                                   # show current registry
$config channel updates <#mention>        # where post_patch_notes posts
$config channel ideas <#mention>          # where check_ideas reads
```

A guild without the relevant channel configured is simply
skipped by that tool — it's an opt-in per guild, per channel
type.

## Picking a database per invocation

Both tools take an optional first positional argument naming
the env var to read for the database name. Default is
`LIVE_DB_NAME`; pass `TEST_DB_NAME` (or any other env var name)
to target somewhere else.

```
python -m tools.post_patch_notes                   # live (default)
python -m tools.post_patch_notes LIVE_DB_NAME      # explicit, same as above
python -m tools.post_patch_notes TEST_DB_NAME      # against local test DB
python -m tools.check_ideas TEST_DB_NAME --limit 20
```

If the named env var isn't set, the tool exits immediately
with a message telling you which var is missing — no silent
fallback to a wrong DB.

## Tools

### `post_patch_notes.py`

Posts a markdown file's contents into every guild's
`updates` channel. Defaults to dry-run.

```
python -m tools.post_patch_notes                 # dry-run, default file
python -m tools.post_patch_notes --post          # actually publish
python -m tools.post_patch_notes --file path.md  # custom source
python -m tools.post_patch_notes --guild 12345   # restrict to one guild
```

Default file is `.patch-notes-scratch.md` in the working
directory — the same file the pre-commit ritual writes to.
Discord's per-message limit is 2000 characters; the tool
refuses oversize blurbs rather than splitting (split manually
or tighten the blurb).

Exit codes:
- `0` — success (or successful dry-run)
- `1` — setup error (no targets, missing token, missing file)
- `2` — partial success (some guilds posted, others failed)

### `edit_patch_notes.py`

Edit a previously-posted patch notes message in place. Same
file/channel discovery as `post_patch_notes` — reads the new
content from `.patch-notes-scratch.md` (or `--file path.md`)
and PATCHes the most recent post per guild that
`post_patch_notes` recorded in
`tools/.last_posted.<DB_ENV_VAR>.json` (gitignored, one file
per database env so a `LIVE_DB_NAME` post and a `TEST_DB_NAME`
post for the same guild can never contaminate each other).

```
python -m tools.edit_patch_notes                       # dry-run
python -m tools.edit_patch_notes --post                # actually edit
python -m tools.edit_patch_notes --file fix.md
python -m tools.edit_patch_notes --message-id 12345 --guild 678
```

Dry-run shows the existing message content next to the new
content so you can sanity-check the diff. `--message-id`
overrides the last-posted lookup (requires `--guild` so we
know which channel) — useful when editing a post made from a
different machine.

Discord limits message edits to messages the bot itself
authored, so a 403 means the target wasn't posted by this
bot. The default flow (last-posted log) avoids that case
entirely; the override path can run into it if you supply an
arbitrary id.

### `check_ideas.py`

Reads new messages from each guild's `ideas` channel since the
last successful run, formats them as planning-ready markdown
(timestamp + author + verbatim content), updates a per-guild
cursor at `tools/.ideas_cursor.json` (gitignored).

```
python -m tools.check_ideas                # incremental
python -m tools.check_ideas --limit 100    # first-run window
python -m tools.check_ideas --reset        # clear cursor
python -m tools.check_ideas --guild 12345  # restrict to one guild
```

First run for a guild has no cursor, so the tool pulls the most
recent `--limit` messages (default 50) and seeds. Subsequent
runs use `after=<last_seen>` so the same message is never
returned twice. A guild whose REST call fails has its cursor
left untouched — next run retries from the same point.

The output format is intentionally markdown-clean for paste-back
into a planning conversation; it doesn't need summarization
before being consumed by another tool / model.

## Forks

Both tools assume the canonical project schema (the `auth`
collection holds the bot token; the `servers` collection holds
per-guild config under `channels.<key>`). A fork using the same
collections will work as-is. Forks with different DB names just
need the appropriate `LIVE_DB_NAME` (and optionally
`TEST_DB_NAME`) in `.env`.

The bot token in your live `auth` document is the only secret
the tools need; if you're forking publicly, **don't commit your
`.env`** (it's already gitignored at the repo root).

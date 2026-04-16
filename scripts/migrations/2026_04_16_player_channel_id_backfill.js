// One-shot mongosh migration — 2026-04-16
//
// Backfills ``channel_id`` on player documents that pre-date the
// game-scoped-player refactor (2026-04-15). Without this, bulk
// updates fail with E11000 duplicate-key errors: the new compound
// filter ``{guild_id, channel_id, user_id}`` doesn't match legacy
// docs (which lack channel_id), so Mongo treats each save as an
// INSERT and collides on the existing ``_id``.
//
// For each legacy player, look up the (only) game in their guild
// — multi-game-per-guild didn't exist before today's rekey, so
// there's exactly one game per guild in the DB — and stamp its
// ``channel_id`` onto the player doc.
//
// Idempotent: skips players that already have channel_id set.
//
// IMPORTANT: safe to run with the bot online, but cleaner with it
// stopped. With the bot running, concurrent saves on legacy docs
// will keep failing until the backfill overtakes them.
//
// Usage:
//   mongosh "<connection-string>" --file scripts/migrations/2026_04_16_player_channel_id_backfill.js

let touched = 0;
let orphaned = 0;
db.players.find({channel_id: {$exists: false}}).forEach(p => {
  const game = db.games.findOne({guild_id: p.guild_id});
  if (game && game.channel_id) {
    db.players.updateOne(
      {_id: p._id},
      {$set: {channel_id: game.channel_id}}
    );
    touched++;
  } else {
    // Player exists but their guild has no game — orphaned record.
    // Log but don't delete; leave cleanup to a human decision.
    print(`orphaned player _id=${p._id} guild_id=${p.guild_id} (no game in guild)`);
    orphaned++;
  }
});
print(`backfilled ${touched} player document(s); ${orphaned} orphaned`);

// One-shot mongosh migration — 2026-04-16
//
// Deduplicates ``servers`` collection entries that share the same
// guild_id. ``DB.insert_server`` was a raw InsertOne with no
// idempotency, so concurrent insertion paths (on_guild_join +
// get_prefix first-touch) could race and leave multiple rows for
// one guild — and a guild joined/left/rejoined multiple times would
// accumulate one row per join cycle with no cleanup of the prior.
//
// Strategy: for each guild_id with >1 row, pick a canonical row
// (prefers one whose prefix differs from the default "$") and
// delete the rest. Idempotent: no-op on guilds with exactly one row.
//
// Safe to run with the bot online, but quieter with it stopped
// (get_prefix racing with the cleanup could re-insert a deleted
// row during the window — unlikely in practice but possible).
//
// Usage:
//   mongosh "<conn>" --file scripts/migrations/2026_04_16_dedupe_servers.js

let guildIds = db.servers.aggregate([
  {$group: {_id: "$guild_id", count: {$sum: 1}, ids: {$push: "$_id"}}},
  {$match: {count: {$gt: 1}}},
]).toArray();

let collapsed = 0;
let removed = 0;
guildIds.forEach(group => {
  const rows = db.servers.find({guild_id: group._id}).toArray();

  // Prefer a row whose prefix isn't the default "$" (somebody
  // configured a custom prefix and we don't want to lose it).
  // Fall back to the first row if every row has the default.
  let keeper = rows.find(r => r.prefix && r.prefix !== "$") || rows[0];

  const toDelete = rows
    .filter(r => !r._id.equals(keeper._id))
    .map(r => r._id);

  if (toDelete.length > 0) {
    db.servers.deleteMany({_id: {$in: toDelete}});
    collapsed++;
    removed += toDelete.length;
    print(
      `guild_id=${group._id}: kept _id=${keeper._id} (prefix=${keeper.prefix || "$"}), ` +
      `removed ${toDelete.length} duplicate(s)`
    );
  }
});

if (collapsed === 0) {
  print("OK: no duplicate server entries found.");
} else {
  print(`collapsed ${collapsed} guild(s); removed ${removed} duplicate row(s) total`);
}

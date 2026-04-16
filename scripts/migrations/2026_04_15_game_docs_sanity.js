// One-shot mongosh sanity + cleanup — 2026-04-15
//
// The per-game DB API now filters on the compound
// ``{guild_id, channel_id}`` pair. Every game document *should*
// already have ``channel_id`` set (``insert_game`` has written it
// for a long time), but this script:
//
//   1. Reports any game docs missing ``channel_id`` — they'd be
//      invisible to the new ``DB.get_game`` / ``DB.update_game`` /
//      ``DB.delete_game`` queries.
//   2. Unsets any stray legacy ``channelId`` (camelCase) field if
//      it's still lurking on any doc. Code hasn't referenced it in
//      a long time, but the user remembered possibly having it
//      in some records.
//
// No data migration needed beyond the cleanup — just reports the
// broken docs for manual fixup if any exist.
//
// Usage:
//   mongosh "<connection-string>" --file scripts/migrations/2026_04_15_game_docs_sanity.js

// 1. Report docs missing channel_id.
const missingChannelId = db.games
  .find({channel_id: {$exists: false}})
  .toArray();

if (missingChannelId.length > 0) {
  print(`WARNING: ${missingChannelId.length} game document(s) missing 'channel_id':`);
  missingChannelId.forEach(doc => {
    print(`  _id=${doc._id}, guild_id=${doc.guild_id}`);
  });
  print("These games will be invisible to the new per-channel API.");
  print("Backfill channel_id manually or delete the docs if they're stale.");
} else {
  print("OK: every game document has channel_id.");
}

// 2. Strip any legacy camelCase ``channelId`` field.
const legacyResult = db.games.updateMany(
  {channelId: {$exists: true}},
  {$unset: {channelId: ""}}
);

if (legacyResult.modifiedCount > 0) {
  print(`Cleaned up legacy 'channelId' field on ${legacyResult.modifiedCount} document(s).`);
} else {
  print("OK: no legacy 'channelId' fields present.");
}

// One-shot mongosh migration — 2026-04-15
//
// Renames the ``"unarmed"`` skill key to ``"unarmed bludgeoning"``
// so it matches the weapon-skill pattern ("<qualifier> <damage-type-
// canonical>") and round-trips through ``DamageTypes.from_skill_key``
// for uniform emoji / trait lookups.
//
// Merges XP additively if both keys somehow coexist (e.g. a player
// landed a punch after the code change but before this migration
// ran), so no XP is lost regardless of ordering.
//
// Idempotent — re-running the script on a document that already has
// only "unarmed bludgeoning" is a no-op.
//
// IMPORTANT: stop the bot before running, or write activity during
// migration may produce keys in the new form alongside the old —
// migration would still merge them additively, but cleaner to
// run in a quiet window.
//
// Usage:
//   mongosh "<connection-string>" --file scripts/migrations/2026_04_15_unarmed_bludgeoning.js

let touched = 0;
db.players.find({"skills.unarmed": {$exists: true}}).forEach(p => {
  const oldXp = p.skills["unarmed"] || 0;
  const existingNewXp = p.skills["unarmed bludgeoning"] || 0;
  const merged = oldXp + existingNewXp;

  db.players.updateOne(
    {_id: p._id},
    {
      $set: {"skills.unarmed bludgeoning": merged},
      $unset: {"skills.unarmed": ""},
    }
  );
  touched++;
});
print(`migrated ${touched} player document(s)`);

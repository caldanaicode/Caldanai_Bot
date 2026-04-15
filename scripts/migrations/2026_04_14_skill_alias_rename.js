// One-shot mongosh migration — 2026-04-14
//
// Renames legacy elemental-combo skill keys in player documents to
// use the new compound aliases that ship with the DamageTypes enum:
//
//   "dark water"  → "ice"        (DARK | WATER | COMBINED)
//   "dark air"    → "poison"     (DARK | AIR | COMBINED)
//   "light air"   → "lightning"  (LIGHT | AIR | COMBINED)
//   "earth water" → "acid"       (EARTH | WATER | COMBINED)
//
// Idempotent — running twice is a no-op (already-migrated keys
// don't match the legacy patterns). XP from a legacy key folds into
// the new-form key on collision (additive).
//
// Run order: this script is safe to run before OR after deploying
// the alias-aware code — the renamed keys persist in either case.
//
// Usage:
//   mongosh "<connection-string>" --file scripts/migrations/2026_04_14_skill_alias_rename.js

const renames = [
  ["dark water",  "ice"],
  ["water dark",  "ice"],
  ["dark air",    "poison"],
  ["air dark",    "poison"],
  ["light air",   "lightning"],
  ["air light",   "lightning"],
  ["earth water", "acid"],
  ["water earth", "acid"],
];

let touched = 0;
db.players.find({"skills": {$exists: true}}).forEach(p => {
  const merged = {};
  let changed = false;
  for (const [key, xp] of Object.entries(p.skills)) {
    let newKey = key;
    for (const [old, neu] of renames) {
      if (newKey.includes(old)) newKey = newKey.replace(old, neu);
    }
    if (newKey !== key) changed = true;
    merged[newKey] = (merged[newKey] || 0) + xp;
  }
  if (changed) {
    db.players.updateOne({_id: p._id}, {$set: {skills: merged}});
    touched++;
  }
});
print(`migrated ${touched} player document(s)`);

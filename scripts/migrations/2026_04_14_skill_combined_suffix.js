// One-shot mongosh migration — 2026-04-14 (run #2)
//
// Backfills the canonical " combined" suffix on player skill keys
// generated from COMBINED-bit weapons that lack a compound alias.
// Pre-2026-04-14 the ``DamageTypes.__str__`` silently dropped the
// COMBINED bit; the new canonical form preserves it as the word
// "combined" in skill keys so that COMBINED-bit damage types don't
// share storage keys with hypothetical non-COMBINED counterparts.
//
// Affects existing players who used:
//   - torch  → "one-handed bludgeoning fire" → "...bludgeoning fire combined"
//   - bow    → "one-handed ranged piercing"   → "...ranged piercing combined"
//   - wand   → "one-handed ranged magical"    → "...ranged magical combined"
//
// Idempotent — strict suffix match means already-migrated keys
// (with " combined" already appended) won't double-append.
//
// IMPORTANT: stop the bot before running, or write activity during
// migration may produce keys in the new form alongside the old —
// migration would still merge them additively, but cleaner to
// run in a quiet window.
//
// Usage:
//   mongosh "<connection-string>" --file scripts/migrations/2026_04_14_skill_combined_suffix.js

const SUFFIX_TARGETS = [
  "bludgeoning fire",  // torch
  "ranged piercing",   // bow
  "ranged magical",    // wand
];

let touched = 0;
db.players.find({skills: {$exists: true}}).forEach(p => {
  const merged = {};
  let changed = false;
  for (const [key, xp] of Object.entries(p.skills)) {
    let newKey = key;
    for (const target of SUFFIX_TARGETS) {
      // Strict ``endsWith`` → no double-append on already-migrated keys.
      if (newKey.endsWith(target)) {
        newKey = newKey + " combined";
        break;
      }
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

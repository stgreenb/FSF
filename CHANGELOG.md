# Changelog

Notable changes to the Forgesteel↔Foundry converter, newest first.
Detailed contracts live in the linked docs; OpenSpec change names match the
archive under `openspec/changes/archive/`.

## 2026-11-10 — Custom Foundry items survive the print round trip

*Change: `carry-unknown-treasure-to-print` (reverse)*

- Treasures with no provenance and no ForgeSteel match are no longer
  dropped: they are synthesized into `state.inventory` as `defaulted`
  entries from the export's own fields (markdown description, quantity →
  count, category → item-type table with keyword refinement, crafting
  block → `isCustom` crafting entry) with deterministic `custom-<slug>`
  ids. ForgeSteel keeps unknown item ids on save, so custom gear prints,
  survives in-app editing and level-up, and rides forward back to Foundry.
- Custom-subject project items reconstruct as editable custom projects
  (`isCustom: true`) with progress; project items dedupe by name.
- New `mechanical-effects-lost` report warning: reconstructed items whose
  Foundry active effects are pure mechanics (changes, no text — e.g.
  `damage.bonuses.treasure +1`) name each effect and its keys, since no
  text exists to carry them through.
- Ingestion no longer pre-reports `unmappable` for provenance-less
  treasures (the mapper is the authority; blank-name items stay losses).
- Field-tested on live Vistin & Pyre exports: print PDFs OCR-diffed, and
  import → save → export through the players' ForgeSteel build kept every
  item, count, description and project point (`FIELD_TEST.md`).
- Details: `REVERSE_CONVERSION.md` → *Custom items (Foundry-made gear)*.

## 2026-11-02 — Compendium grant reconciliation & granted-ability matching

*Changes: `fix-compendium-grant-reconciliation`, `fix-ancestry-granted-abilities` (forward)*

- New grant-reconciliation post-pass (`converter/grant_reconcile.py`):
  grant-all `Multiple Features` pools expanded, nested Skill Choices
  harvested, above-level grants trimmed (level-evidence cascade),
  case-sensitive dedupe sweep. Addresses GitHub issues #2/#3 (PeterQJ).
- Loader: `CompendiumIndex` (pack name→doc index built once),
  `PACK_PATCHES` in-memory upstream effect-key typo fixes, treasure
  `_dsid: "treasure"` collision fix (unique `_id` fallback).
- Ancestry granted abilities: all 24 pack-granted abilities now resolve;
  sanitized display-name matching fixed (was comparing against dsid slugs);
  blank-name guard; type detection ability-vs-trait fixed.
- Hygiene: `copy.deepcopy` at 8 mutation sites, LevelDetector fallback.
- Details: `FORWARD_CONVERSION_FIXES.md`.

## 2026-10-28 — Projects and inventory round-trip both directions

*Change: `add-project-and-inventory-conversion` (forward + reverse)*

- Forward: hero projects emit Foundry `project` items (points, goal,
  prerequisite/source texts, yield link in canonical v13 UUID form
  `Compendium.<system>.<pack>.Item.<id>`); inventory treasures emit with
  quantity and crafting text.
- Reverse: `state.projects` reconstructed from project items only
  (points-only rule — treasure project blocks never fabricate progress);
  `state.inventory` hydrated from the fs_data dump with corpus fallback;
  identity = name + crafting definition (count is carried state).
- Titles now flow both ways (`hero.state.titles` ⇄ pack `title` items +
  granted features, e.g. Duck!); `titles.json` added to the data dump.
- Fixed: stamina double-count (self-applied pack effects), name-drift
  pairs (Mighty Leaps/Mighty Leap, Headbutter/Headbutt), all treasures
  collapsing under the shared `_dsid: "treasure"` marker.

## 2026-10-27 — Reverse converter: Foundry → ForgeSteel

*Change: `add-foundry-to-forgesteel` (reverse)*

- `foundry_to_forgesteel.py` CLI: exports reverse into `.ds-hero` files
  (ancestry/culture/class/subclass/career/complication, features, perks,
  kits, abilities, level, characteristics, advancement picks, core state,
  titles, `--picture` portrait embedding as base64 data URL).
- Provenance via native `_dsid` with pack name-match fallback; never
  guessed on ambiguity.
- Machine-readable loss report (`<out>.report.json`) with closed
  reason/action/warning vocabulary and `--strict` semantics.
- Payload hydration from the `fs_data` TypeScript dump (cached, SHA-pinned)
  with sample-corpus fallback; structural validation gate.
- Round-trip golden harness (`tests/test_roundtrip.py`) doubles as a
  forward-converter regression oracle.
- Usage and limitations: `REVERSE_CONVERSION.md`.

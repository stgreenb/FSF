# Forward Conversion Fixes — issues #2 / #3 (change fix-compendium-grant-reconciliation)

## Changelog — fix-ancestry-granted-abilities

Ancestry granted abilities (the 24 ability documents under
`origins/Ancestries/*/…Granted_Abilities` in the packs) now convert
reliably:

- Name normalization bridges pack/Forgesteel drift — double spacing
  (`Psionic  Bolt` vs `Psionic Bolt`), unicode punctuation (curly vs
  straight apostrophes), British/American spellings — via
  `TextNormalizer.sanitize_for_compendium_lookup` applied to both display
  names in the compendium ability lookup.
- Bug fixes found while completing this change: the sanitized-match stage
  compared sanitized **index keys** (dsid slugs) to sanitized display names
  and could therefore never hit — it silently relied on a hardcoded
  `known_mappings` entry; a blank ability name matched **every** ability in
  the partial-match stage (now guarded).
- Type detection: ancestry Choice selections that resolve to abilities emit
  `type: ability` (e.g. Time Raider Psionic Gift → Psionic Bolt, formula
  `@chr` intact); true traits keep `type: ancestryTrait`.
- All 24 granted abilities are now covered by a resolution test
  (`tests/test_ancestry_abilities.py::TestPackAncestryAbilities`);
  Psionic Bolt is locked end-to-end on Quistis.
- Normalization rule documentation lives in
  `AbilityConverter._find_compendium_ability`'s docstring (stage list).

---

Finding → behavior → test matrix for the GitHub issues reported by PeterQJ
(stgreenb/FSF #2, #3). Verified against pinned packs `tags/1.1.0` and
compendium shapes from `origin/main`; unit tests in
`tests/test_grant_reconcile.py`, scenarios in
`tests/test_grant_reconciliation.py` (fixtures `tests/fixtures/heroes/`),
loader tests in `tests/test_loader_patches.py`.

| # | Finding (issue) | Implemented behavior | Test |
|---|-----------------|----------------------|------|
| 2-1 | Runic Carving choice mismatches (fuzzy substring `Light` → Lightning Nimbleness) | Substring compendium fallback hardened; an ancestry `Choice` with no exact trait match emits the **parent trait** with `Selected: <option>` in the description instead of a wrong item | `test_rune_voice_emits_parent_trait_not_fuzzy_match`, `test_parent_trait_records_selection`, `test_rune_option_light_also_resolves_to_parent`, `test_no_lightning_nimbleness` |
| 2-2 | Stamina double-count via Bonus feature whose pack item self-applies; nested naming (`Prayer` > `Prayer of Steel` > `Stamina`) | Self-application skip matches the **enclosing feature chain** (`_enclosing_names` propagated through expansion), not just the Bonus' own name; scan runs after all item passes (landed earlier in `0e9d067`) | `test_expand_records_enclosing_names`, `test_nested_bonus_skipped_when_item_applies_stamina` |
| 2-3 | Forward choice-option asymmetry vs reverse | Reverse recovers `Selected:`-named options from the sample corpus and re-attaches them to the parent Choice (recovered-by-name report entry) | round-trip oracle (`tests/test_roundtrip.py::test_keth` Voice/Light paths) |
| 3.1 | Grant-all `itemGrant` pools (Null Speed, Metakinetic Mastery) dropped | Reconciliation grant-all step emits every pool member ≤ hero level, level-gated also by hero-side above-level evidence | `test_grant_all_pools_completed` (16 items restored on Null lvl 1) |
| 3.2 | Level-filter leak: `Blessed Domain` (lvl 4) emitted on level-1 hero | Trim step: keep-if-any-grant, never trim blind, container-unit cascade; same evidence re-gates grant-all injection so trimmed items are never re-added | `test_above_level_dropped`, `test_no_above_level_items` |
| 3.3 | Package+Choice double emission (`Prayer of Steel` twice, stamina applied twice) | Case-sensitive `(name, type)` dedupe with `X - Activate` dsid exception; final sweep after all injections | `test_exact_duplicate_collapses`, `test_activate_pair_survives`, `test_prayer_of_steal_single_instance` |
| 3.4 | Conduit domain picks not emitted | choose-N pool emission matched by pick name ∈ pool (feature name ≠ advancement carrier) | `test_chosen_domains_present_as_subclass_items` |
| 3.5 | Nested Skill Choices (Navigate/Escape Artist/Culture) dropped | Skill harvest unions hero-recorded picks into `system.hero.hero.skills`, order-stable | `test_skill_harvest` |
| 3.6 | Summon Choices become featureless placeholders; module expects Actor-UUID flags | Summon picks → `flags.draw-steel.advancement.<id>.selected` with compendium Actor UUIDs via the loader name index; unresolvable pick = warning + **no** partial flags (never fabricated). Positive path requires a summons pack (packs ≥ 1.2); pinned 1.1.0 asserts no-fabrication | `test_summon_flags_all_or_nothing`, `test_unresolvable_summon_never_fabricated` |
| 3.7 | Ancestry `Damage Modifier` placeholder (Revenant) | Deferred to the pending damage-modifier pass (same as class path); immunity/weakness still applied, no featureless item | `test_no_placeholder_trait`, `test_no_damage_modifier_placeholder` |
| 3.8 | Blank hero name | Loader falls back to the `.ds-hero` filename stem (single seam) | `test_blank_name_uses_filename` |
| — | Level single-source-of-truth | `class.level` wins, `LevelDetector` fallback when absent (was: dead compute + silent default 1) | `test_missing_class_level_falls_back_to_detector` |
| — | Shared-compendium mutation | All compendium-item copies into output are `deepcopy` (mapper + ability converter) | `TestCompendiumImmutable` |
| — | `os.walk` packs fallback in `_process_item_advancements` | Replaced by `CompendiumIndex.resolve_by_uuid` (index built once at load) | `test_resolve_by_uuid_roundtrip`, `test_unknown_uuid_returns_none` |
| — | Upstream compendium key typos | `PACK_PATCHES` loader patches (see below) | `test_pack_patches`, `test_pack_patches_no_false_positive`, `test_pack_patches_summoner_strike` |

## Upstream compendium typos (FYI — patched in-memory, upstream files untouched)

Both filed upstream in the Draw Steel module tracker per the issue thread;
`converter/loader.py::PACK_PATCHES` applies them at load time:

- **Null Field — Synaptic Break**: `system.characteristics.might.intuition`
  should be `system.characteristics.intuition.resist` (wrong key shape made
  the resistance a no-op).
- **Summoner Strike**: `flags-draw-steel.summoner-strike-range` should be
  `flags.draw-steel.summoner-strike-range` (hyphen-nested flags key).

Patches are in-memory only (exported actors keep upstream keys until their
next pack refresh), doc-guarded, and keyed by pack folder + document name.

## Known gaps (forward → reverse, post-reconciliation)

- **Conduit domain picks**: forward now emits the chosen domains as pack
  `subclass` items; the reverse mapper cannot yet route `subclass` items
  back into a Conduit `Domain` feature's selection (Conduit has no static
  subclass list — domains live in `domains.json`). Exported heroes report
  `payload-unavailable: subclass unresolved` and the domains must be
  re-picked in ForgeSteel. Follow-on candidate: route via domains.json name
  match into the Domain feature's `data.selected`.
- **Summon flags positive path**: needs a ≥1.2 packs pin (no summons pack
  in 1.1.0). Behavior with the pin: warn + no flags, never fabricated UUIDs.
- choose-N pool uuids referencing documents absent from the pinned packs
  (added in 1.2) log `unresolvable; skipping` warnings — pin bump when the
  players move to 1.2.

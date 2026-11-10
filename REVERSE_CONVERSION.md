# Reverse Conversion — Foundry VTT → ForgeSteel

Converts a Foundry VTT Draw Steel actor export back into a ForgeSteel
`.ds-hero` file, so characters leveled in Foundry can be reviewed in the
ForgeSteel level-up panels and printed with ForgeSteel's print sheets.

Typical cadence: play in Foundry → every couple of months export the actors
→ reverse-convert → review the loss report → open the `.ds-hero` in the
players' ForgeSteel app.

Forward-direction changes that landed during this work (affect every
conversion, not just reverse):

- **Dwarf stamina double-count fixed**: the 1.1 packs carry the dwarf echelon
  stamina natively on *Spark Off Your Skin*; the converter no longer adds a
  duplicate flat bonus. Re-convert any dwarf actor converted before this fix
  (they exported with +6 phantom max stamina per echelon).
- **Titles convert**: `state.titles` now emits Foundry `title` items plus each
  title's granted features (e.g. Angler, Brawler → Duck!).
- **Treasures are pack-native now**: all treasure pack files shared
  `_dsid: "treasure"`, which collapsed them in the compendium loader; the
  loader falls back to the unique `_id` on collisions, so named treasures
  (Executioner's Blade, Blade of Quintessence...) resolve to their pack
  entries with leveled text in the description.
- **Project conversion**: `state.projects` ⇄ Foundry `project` items —
  goal/points/prerequisite & source texts round-trip; crafting progress is
  read only from project items.
- **Inventory conversion**: treasures reverse into `state.inventory`
  hydrated from the ForgeSteel data dump (leveled definitions + crafting);
  unknown homebrew loot is synthesized from the item's own fields as a
  `defaulted` entry (see [Custom items](#custom-items-foundry-made-gear));
  ambiguous name matches are reported, never guessed.
- **Yield links use canonical v13 UUIDs**
  (`Compendium.draw-steel.rewards.Item.<id>`) — Foundry silently drops
  project items whose `yield.document` segment is wrong.

## Prerequisites (one-time)

Both upstream checkouts must exist next to this file and be pinned to the
versions the players actually run:

- `draw_steel_repo/` — pinned to the Foundry module version in use
  (currently `tags/1.1.0`; the converter pack index and skill-group config
  are read from here).
- `forgesteel_repo/` — the ForgeSteel app checkout matching the players'
  app version. Only read, never modified.

Build the ForgeSteel pseudo-data dump (see below) once per ForgeSteel
release the players adopt.

## Usage

```bash
python foundry_to_forgesteel.py <export>.json <out>.ds-hero
```

In Foundry: right-click the actor → **Export JSON**. That file is the input.

Every successful run writes:

- `<out>.ds-hero` — importable into the ForgeSteel app
- `<out>.report.json` — machine-readable loss report + summary on stdout

Useful flags:

| Flag | Effect |
|------|--------|
| `--strict` | exit non-zero when any item was lost (output is still written) |
| `--debug` | on structural validation failure, save `<out>.rejected.json` |
| `--picture IMAGE` | embed an image file as the hero portrait (ForgeSteel stores portraits as base64 data URLs; Foundry exports only carry the asset *path*, so pass the original image file if you want the portrait to ride through) |
| `--fs-data PATH` | use a specific fs_data dump directory |
| `--packs PATH` | pinned compendium pack directory (name-match index) |
| `--corpus GLOB` | sample `.ds-hero` files used as the payload fallback cache |

### Whole roster in one pass

Batch mode is deliberately not part of the CLI; a shell loop covers the
four-character roster:

```bash
for f in exports/*.json; do
    python foundry_to_forgesteel.py "$f" "out/$(basename "${f%.json}").ds-hero"
done
```

## Known limitations (verified against live exports)

- **Project satisfaction flags**: Foundry's project schema has no field for
  prerequisite/source satisfaction; only the texts and points round-trip,
  and reversed projects default the two satisfaction flags to false.
- **Project progress rides both ways**: crafting points, goal, and
  prerequisite/source wording travel forward (as Foundry project items)
  and back; progress is read only from `project` items, never from a
  treasure's embedded crafting block (which would double-count).

- **Perk slot pairing**: the Foundry module models a Perk choice as an
  `itemGrant` advancement that never records which item was granted, and
  perk items carry no back-link to their granting definition. When two
  perks share a list (e.g. two Exploration perks, one from career and one
  from a class perk slot), the reverse may assign them to the slots in the
  wrong order. Both perks always survive; eyeball which slot shows which.
- **App-synthesized choice options**: some choices exist only inside hero
  files (e.g. the dwarf 'Runic Carving' rune options Detection / Light /
  Voice) — static data stores them as markdown inside a Text feature. The
  reverse recovers the picked option's payload from the sample corpus and
  attaches it as its own trait feature with a `defaulted` report entry;
  re-select the option in ForgeSteel if you want it under its choice.
- **Unrecordable picks**: some Foundry choices are never written to the
  export at all (e.g. the Elementalist Enchantment pick, career inciting
  incidents). These are reported as `defaulted` losses and must be re-picked
  once in ForgeSteel.

## Custom items (Foundry-made gear)

A treasure with no provenance and no ForgeSteel/`fs_data` name match is no
longer dropped: the reverse **synthesizes a `defaulted` `state.inventory`
entry** from the item's own fields — name, HTML description converted to
markdown, `quantity` → `count`, and a card-correct item type derived from
the Foundry category (`consumable` → Consumable Item, `trinket` → Trinket
(1st echelon), `artifact` → Artifact, `leveled` → refined by keyword to
Leveled Weapon/Armor/Implement, anything unknown → `Leveled Item`). A
`project` item for a custom subject becomes an **editable custom project**
(`isCustom: true`) carrying its points. ForgeSteel keeps unknown inventory
ids on save (`hero-update-logic` returns the original item), so the entry
survives opening, editing, level-up and printing in the app, and rides
forward back to Foundry as a treasure.

Boundaries to know:

- **Text fidelity only.** Fields come exclusively from the export; no
  power rolls or leveled effects are invented. A GM weapon whose bonus
  lives in a Foundry active effect (e.g. `+1 damage` with no description
  text) prints as lore only — the conversion flags it with a
  `mechanical-effects-lost` warning naming each effect and its changed
  keys, so nothing disappears silently; re-apply the number in Foundry
  after re-import.
- **Type is a heuristic.** A `leveled` treasure without a
  Weapon/Armor/Implement keyword lands on the generic `Leveled Item`
  card; the report detail names the chosen type.
- **Ambiguous names are never reconstructed** — a name matching several
  dump items stays a `payload-unavailable` loss (identity is never guessed).
- **Quantity 0** (a spent stack) comes back as count 1 — Foundry exports
  the item, so it is treated as present.
- Synthetic ids are deterministic (`custom-<slug>`, hash-suffixed on
  name collision): re-converting the same export gives identical files.
- Escape hatch if a card ever renders oddly in a player's ForgeSteel
  build: move the item's text into a plain Text feature under `features`
  (always prints) and delete the synthetic inventory entry.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success (read the loss report even on 0) |
| 1 | fatal input error (not an actor export, bad JSON, unresolvable class, or structural validation failure) — no output written |
| 2 | `--strict` and the conversion had losses |

## Refreshing the ForgeSteel data dump

The converter reads ForgeSteel's pseudo-data (ancestry/class/career/culture/
perk/kit/complication objects) from a JSON dump of `forgesteel_repo/src/data/`,
cached under `~/.cache/forgesteel-converter/fs_data/<git-sha>/`. Refresh it
whenever the players upgrade ForgeSteel:

```bash
cd forgesteel_repo && npm ci
node node_modules/esbuild/install.js        # npm 12 blocks esbuild's postinstall
npx esbuild src/data/sourcebook-data.ts --bundle --platform=node --format=esm \
    --outfile=/tmp/opencode/fs-data-bundle.mjs --tsconfig=tsconfig.app.json
npx esbuild ../tools/fs-data-dump/dump.ts --bundle --platform=node --format=esm \
    --outfile=/tmp/opencode/fs-dump.mjs
node /tmp/opencode/fs-dump.mjs            # writes ./fs_data (or --out <dir>)
```

Then install the fresh dump into the SHA-keyed cache (run from the FSF repo
root, where `./fs_data` was written):

```bash
python -c "from converter.reverse.fs_data_cache import install_dump, current_repo_sha; \
print(install_dump('fs_data', current_repo_sha('forgesteel_repo')))"
```

Or skip the cache and point at the directory directly with `--fs-data
fs_data`. The CLI warns (`dump-stale`) when the cached
dump's SHA no longer matches `forgesteel_repo` HEAD — with four actors you can
ignore the warning for a normal session, but refresh before triaging odd
payload losses.

## Version pinning rules

- The export comes from the module version your world runs; the pinned
  `draw_steel_repo` checkout must match it (provenance format stability is
  tied to it).
- The fs_data dump must be built from the ForgeSteel checkout matching the
  app the players open. `_dsid`s are stable across minor versions, but new
  content only resolves with a fresh dump.
- Sample `.ds-hero` files at the repo root double as a payload fallback
  cache; keep the files the players last exported from ForgeSteel around.

## Reading the loss report

`<out>.report.json` has three parts:

- `losses[]` — per item: `item`, `type`, `dsid`, `reason`, `action`, `detail`.
  Reasons: `unmappable` (no provenance, no name match **and nothing
  extractable** — e.g. a blank-name treasure; re-create manually in the app),
  `payload-unavailable` (no ForgeSteel data for the resolved dsid, or an
  ambiguous name match — never guessed), `unsupported-construct` (extra
  classes — multi-classing is not representable in `.ds-hero`),
  `version-mismatch`, `defaulted` (two flavors: an unmade choice with a safe
  stand-in, e.g. the career inciting incident — **or** a custom item
  synthesized from the export's own fields, see
  [custom items](#custom-items-foundry-made-gear)).
- `warnings[]` — informational; never fail `--strict`: `payload-divergence`,
  `state-reset`, `setting-uncertain`, `dump-stale`, `unrepresentable-picture`,
  `mechanical-effects-lost` (a reconstructed custom item carries Foundry
  active effects that are pure mechanics — e.g. `damage.bonuses.treasure
  +1` with no description text — so they cannot ride the text-fidelity
  round trip; the warning names each effect and its changed keys, and the
  bonus must be re-applied manually in Foundry after re-import).
- `counts` — per-category converted/dropped tallies.

### Roster triage cheat-sheet

- **inciting incident `defaulted`** — Foundry never records it. The player
  re-picks it on the ForgeSteel career panel; printed sheets show the choice.
- **`defaulted … re-select in ForgeSteel`** — the choice had no evidence in
  the export (e.g. the Elementalist Enchantment pick is not exported by the
  module at all). The slot shows unfilled in the app; re-select.
- **`unmappable`** — check whether the item is homebrew; if it is a renamed
  official item, restore its original name in Foundry and re-export.
- **`payload-unavailable` treasure/project** — an ambiguous double match
  (name resolves to several ForgeSteel items) or project data with nothing
  to hydrate from. Projects still ride with progress rebuilt from the export
  item alone — re-check the wording in ForgeSteel. Unmatched treasures are
  no longer in this bucket: they are synthesized as `defaulted` entries
  (see [Custom items](#custom-items-foundry-made-gear)).
- **project satisfaction flags** — ForgeSteel tracks whether a project's
  prerequisites/source were satisfied; the Foundry module has no field for
  that, so reversed projects default those flags to false. Re-tick them in
  ForgeSteel if they were satisfied (points/goal are unaffected).

## State convention: full-rest

The generated `.ds-hero` always lands in rested state (`staminaDamage: 0`,
`recoveriesUsed: 0`, no conditions) — ForgeSteel derives stamina/recoveries
from the build itself. Persistent scalars do carry over: `xp`, `surges`,
`victories`, `renown`, `wealth`, `heroTokens`, and project points (crafting
progress is build state, not combat state). If the export was made mid
adventure (stamina damage or statuses present), a `state-reset` warning
appears in the report; the transient values are intentionally not carried.

## Fidelity guarantees (what is never guessed)

- Build choices are recovered from item provenance (`_dsid`) — native
  ForgeSteel provenance shipped by the official module — never from names
  when a dsid exists.
- Derived numbers (stamina totals, immunity tiers, characteristic bonuses
  above what the export states) are never copied; ForgeSteel re-derives
  them from the restored choices.
- Unresolvable subclasses are left unselected and reported, never guessed.
- Multi-classed actors convert the first class only; the rest is reported.

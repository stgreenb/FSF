# Reverse Conversion — Foundry VTT → ForgeSteel

Converts a Foundry VTT Draw Steel actor export back into a ForgeSteel
`.ds-hero` file, so characters leveled in Foundry can be reviewed in the
ForgeSteel level-up panels and printed with ForgeSteel's print sheets.

Typical cadence: play in Foundry → every couple of months export the actors
→ reverse-convert → review the loss report → open the `.ds-hero` in the
players' ForgeSteel app.

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
  Reasons: `unmappable` (no provenance, no name match — usually homebrew;
  re-create manually in the app), `payload-unavailable` (no ForgeSteel data
  for the resolved dsid), `unsupported-construct` (extra classes — multi-classing is not
  representable in `.ds-hero`), `version-mismatch`, `defaulted` (an unmade
  choice with a safe stand-in, e.g. the career inciting incident).
- `warnings[]` — informational; never fail `--strict`: `payload-divergence`,
  `state-reset`, `setting-uncertain`, `dump-stale`, `unrepresentable-picture`.
- `counts` — per-category converted/dropped tallies.

### Roster triage cheat-sheet

- **inciting incident `defaulted`** — Foundry never records it. The player
  re-picks it on the ForgeSteel career panel; printed sheets show the choice.
- **`defaulted … re-select in ForgeSteel`** — the choice had no evidence in
  the export (e.g. the Elementalist Enchantment pick is not exported by the
  module at all). The slot shows unfilled in the app; re-select.
- **`unmappable`** — check whether the item is homebrew; if it is a renamed
  official item, restore its original name in Foundry and re-export.

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

# Field Tests

## carry-unknown-treasure-to-print — Vistin & Pyre (2026-11-10) — PASSED

Pipeline: live Foundry exports (`fvtt-Actor-vistin-*.json`,
`fvtt-Actor-pyre-*.json`) → `foundry_to_forgesteel.py` → import into the
players' ForgeSteel build → print PDFs → export `.ds-hero` back out of the
app (`Vistin-from-fs.ds-hero`, `Pyre-from-fs.ds-hero`).

Verified mechanically (OCR of the print PDFs vs. the converted files, and
input-vs-app-export diffs):

- **Synthesis completeness**: Pyre 11/11 inventory items (8 synthesized
  customs incl. two leveled weapons with crafting defs), Vistin 8/8
  (Silver Hatchet synthesized). Counts carried (sheets of glass = 3).
- **Print fidelity**: every item name + description renders on the sheet
  (names, keywords, type line, full effect text); both renamed downtime
  projects print with progress (183, 125). Consumable custom text prints
  identically to book items.
- **App round-trip durability**: every item and project — synthetic and
  known — survived import → save → export with ids, counts, descriptions,
  crafting defs and project points intact (`return origItem` behavior
  confirmed on the players' build).
- Known item ids (`item-*`) stable across the app trip; synthetic
  `custom-*` ids stable as well.

Notes:

- The players' ForgeSteel build rewrites legacy enum value
  `Consumable Item` → `Consumable (1st echelon)` on save — app-side
  data-refresh normalization, lossless; our pinned checkout
  (96302a09) still labels the enum `Consumable Item`. Watch upstream
  `item-type.ts` at the next dump refresh.
- The app drops `customizationsByLevel` from saved items it doesn't know
  customization keys for — harmless (empty in our output).
- Crafting goal numbers surface in the projects print section, not on
  item cards — ForgeSteel template behavior, not a conversion gap.
- Print PDFs are image-only (html2canvas/jspdf): verification harness is
  `pdftoppm -r 200` + `tesseract` + text diff against the `.ds-hero`.

## Keth (2026-10-27) — see git history of add-foundry-to-forgesteel

First live round trip: titles, stamina, XP carry, picture embedding;
pre-dates custom-item synthesis.

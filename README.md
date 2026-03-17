# Forgesteel to Foundry VTT Converter

Convert Draw Steel characters from Forgesteel (.ds-hero files) into Foundry Virtual Tabletop format for the Draw Steel system module.

## Quick Start

**Use ONLY this command:**
```bash
python forgesteel_converter.py your_character.ds-hero converted_character.json
```

**DO NOT USE:** `converter/mapper.py` or other files in the converter directory - these are internal modules.

## Installation

1. Clone or download this repository
2. Install Python 3.6+ (if not already installed)

The converter automatically fetches the Draw Steel compendium using a hybrid approach:
- Local first (if you have `draw_steel_repo/src/packs` or specify `--compendium`)
- Cache for faster subsequent runs
- GitHub fallback (automatic, no setup required)

## Usage

```bash
# Basic conversion
python forgesteel_converter.py character.ds-hero character.json

# With local compendium (faster, offline)
python forgesteel_converter.py character.ds-hero character.json --compendium /path/to/draw-steel/src/packs

# Debug mode
python forgesteel_converter.py character.ds-hero character.json --verbose

# Strict mode (fail on missing items)
python forgesteel_converter.py character.ds-hero character.json --strict
```

## Importing into Foundry VTT

1. Open your Foundry world
2. Go to the **Actors** sidebar tab
3. Right-click and select **Import Data**
4. Choose your converted JSON file

## Features

- Complete character conversion (attributes, abilities, features, items)
- Smart compendium lookup with type-based matching
- Character encoding normalization (handles special characters)
- Multi-source level detection with validation
- Enhanced description transfer with markdown-to-HTML conversion
- Quality validation and comprehensive reporting
- Proper advancement mapping for skills and languages
- Movement calculation with ancestry bonuses
- Resource tracking (recoveries, stability, heroic resources)

## What Gets Converted

**Character Data:** Attributes, stamina/health, recovery/stability, movement speed, biography

**Items & Features:** Ancestry, culture, career, class, subclass, abilities, features, projects, complications, equipment

**Knowledge & Skills:** Skill selections, languages, perks, domains

## Troubleshooting

**"File not found"** - Verify the .ds-hero file path is correct

**Compendium fetch fails** - Check internet connection or use local compendium with `--compendium`

**Missing items** - Use `--verbose` to see lookup details

**GitHub API limit** - 60 requests/hour for unauthenticated users. Use local compendium for bulk conversions

## Dependencies

- Python 3.6+
- Forgesteel character files (.ds-hero)
- Draw Steel compendium (automatically fetched)

No external Python packages required - uses only standard library.

## Compatibility

Tested with Draw Steel Foundry VTT system v0.10+. Compatible with v0.11.x.

## Known Limitations

- Only converts one selected subclass (Forgesteel limitation)
- Items not in compendium become placeholders
- PDF exports not supported (use .ds-hero format)

## Contributing

Report issues with:
- Your Forgesteel character file
- Verbose converter output
- Expected vs actual results

## License

This converter works with the Draw Steel system by MCDM for Foundry Virtual Tabletop. Ensure you have appropriate licenses for both Forgesteel and Foundry VTT.

## Support

- **Converter:** Check CONVERTER_IMPROVEMENTS.md
- **Forgesteel:** [Documentation](https://github.com/andyaiken/forgesteel)
- **Draw Steel:** [Module](https://github.com/MetaMorphic-Digital/draw-steel)
- **Foundry VTT:** [Documentation](https://foundryvtt.com/document/)
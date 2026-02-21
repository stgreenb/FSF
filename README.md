# Forgesteel to Foundry VTT Converter

Convert Draw Steel characters from Forgesteel (.ds-hero files) into Foundry Virtual Tabletop format for the Draw Steel system module.

## Quick Start (GUI - Recommended)

The easiest way to use the converter is the graphical interface. No experience required.

### Step 1: Download

1. Go to the GitHub repository page
2. Click the green **Code** button near the top-right
3. Select **Download ZIP**
4. Open the downloaded `.zip` file and **extract all** to a folder of your choice (e.g. your Desktop or Documents)

### Step 2: Unblock the Script

Windows may block files downloaded from the internet. Before running:

1. Right-click **`Run-ForgesteelGUI.ps1`** and select **Properties**
2. At the bottom of the General tab, check the **Unblock** checkbox
3. Click **Apply** then **OK**

### Step 3: Run

1. Open the extracted folder
2. Right-click **`Run-ForgesteelGUI.ps1`** and select **"Run with PowerShell"**
3. The script will automatically:
   - Check if Python is installed (and install it for you if it isn't)
   - Install any dependencies
   - Launch the GUI
4. Browse for your `.ds-hero` file, set an output path, and click **Convert**

> **First time running a PowerShell script?** If you get an "execution policy" warning, open PowerShell as Administrator and run:
> ```powershell
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then try right-clicking the script again. You only need to do this once.

### Manual GUI Launch

If you already have Python 3.6+ installed you can skip the PowerShell launcher:
```bash
python forgesteel_gui.py
```

## Quick Start (Command Line)

**Use ONLY this command:**
```bash
python forgesteel_converter.py your_character.ds-hero converted_character.json
```

**DO NOT USE:** `converter/mapper.py` or other files in the converter directory - these are internal modules.

## Installation

1. Download the repository as a ZIP (green **Code** button > **Download ZIP**) and extract it, or clone it with `git clone`
2. Install Python 3.6+ (if not already installed)
   - **Windows (easy):** Just run `Run-ForgesteelGUI.ps1` — it handles everything
   - **Manual:** Download from [python.org](https://www.python.org/downloads/) (check "Add Python to PATH" during install)

The converter automatically fetches the Draw Steel compendium using a hybrid approach:
- Local first (if you have `draw_steel_repo/src/packs` or specify `--compendium`)
- Cache for faster subsequent runs
- GitHub fallback (automatic, no setup required)

## Usage

### GUI Mode

Run **`Run-ForgesteelGUI.ps1`** (right-click > Run with PowerShell) or:
```bash
python forgesteel_gui.py
```

The GUI provides:
- File browser for input/output selection
- Checkboxes for verbose logging, strict mode, and force-update compendium
- Live log output showing conversion progress
- Built-in help dialog (click the **?** button)

### Command Line Mode

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

**PowerShell won't run the script** - You may need to set the execution policy:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**"Python was installed but cannot be found in PATH"** - Close the PowerShell window and run the script again. The new PATH takes effect in a fresh session.

**"File not found"** - Verify the .ds-hero file path is correct

**Compendium fetch fails** - Check internet connection or use local compendium with `--compendium`

**Missing items** - Use `--verbose` (CLI) or check **Verbose logging** (GUI) to see lookup details

**GitHub API limit** - 60 requests/hour for unauthenticated users. Set a `GITHUB_TOKEN` environment variable for 5,000/hour, or use a local compendium for bulk conversions

## Dependencies

- Python 3.6+
- Forgesteel character files (.ds-hero)
- Draw Steel compendium (automatically fetched)

No external Python packages required - uses only standard library.

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
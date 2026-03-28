<#
.SYNOPSIS
    Launches the Forgesteel to Foundry VTT Converter GUI.

.DESCRIPTION
    This script checks for a Python installation, installs Python if missing,
    installs any pip requirements, and launches the Forgesteel GUI.

    Right-click this file and select "Run with PowerShell" to get started.
#>

# --- Run from the script's own directory no matter how it was launched --------
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# --- Helpers -----------------------------------------------------------------
function Write-Banner {
    param([string]$Message)
    $line = "=" * 60
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "[*] $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Red
}

function Pause-Exit {
    param([int]$Code = 1)
    Write-Host ""
    Write-Host "Press any key to exit..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit $Code
}

# --- Locate Python -----------------------------------------------------------
function Find-Python {
    # Try common commands in order of preference
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $output = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $output -match "Python\s+(\d+\.\d+)") {
                $ver = [version]$Matches[1]
                if ($ver -ge [version]"3.6") {
                    return $cmd
                }
            }
        }
        catch {
            # Command not found - continue to next
        }
    }
    return $null
}

# --- Install Python via winget ------------------------------------------------
function Install-PythonWinget {
    Write-Step "Attempting to install Python via winget..."
    try {
        $wingetCheck = Get-Command winget -ErrorAction Stop
    }
    catch {
        Write-Fail "winget is not available on this system."
        return $false
    }

    try {
        & winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Python installed successfully via winget."
            return $true
        }
        else {
            Write-Fail "winget install exited with code $LASTEXITCODE."
            return $false
        }
    }
    catch {
        Write-Fail "winget install failed: $_"
        return $false
    }
}

# --- Install Python via direct download --------------------------------------
function Install-PythonDirect {
    Write-Step "Detecting system architecture..."

    $pyVersion = "3.12.8"
    $arch = $env:PROCESSOR_ARCHITECTURE
    switch ($arch) {
        "ARM64"  { $suffix = "arm64" }
        "x86"    { $suffix = "win32" }  # 32-bit Windows
        default  { $suffix = "amd64" }  # AMD64 / x64
    }

    $installerUrl = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-$suffix.exe"
    Write-Step "Downloading Python $pyVersion ($suffix) from python.org..."
    $installerPath = Join-Path $env:TEMP "python-installer.exe"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing -ErrorAction Stop
    }
    catch {
        Write-Fail "Failed to download Python installer: $_"
        return $false
    }

    Write-Step "Running Python installer (this may take a minute)..."
    try {
        $proc = Start-Process -FilePath $installerPath `
            -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1", "Include_tcltk=1" `
            -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            Write-Ok "Python installed successfully."
            return $true
        }
        else {
            Write-Fail "Installer exited with code $($proc.ExitCode)."
            return $false
        }
    }
    catch {
        Write-Fail "Failed to run installer: $_"
        return $false
    }
    finally {
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    }
}

# --- Refresh PATH after install -----------------------------------------------
function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path    = "$userPath;$machinePath"
}

# ==============================================================================
#  MAIN
# ==============================================================================
Write-Banner "Forgesteel to Foundry VTT Converter"

# ---- Step 1: Check for Python ------------------------------------------------
Write-Step "Checking for Python installation..."
$pythonCmd = Find-Python

if ($pythonCmd) {
    $verOutput = & $pythonCmd --version 2>&1
    Write-Ok "Found: $verOutput (command: $pythonCmd)"
}
else {
    Write-Fail "Python 3.6+ is not installed."
    Write-Host ""
    Write-Step "Python is required. Attempting automatic installation..."

    $installed = Install-PythonWinget
    if (-not $installed) {
        $installed = Install-PythonDirect
    }

    if (-not $installed) {
        Write-Host ""
        Write-Fail "Automatic installation failed."
        Write-Host "  Please install Python manually from https://www.python.org/downloads/" -ForegroundColor White
        Write-Host "  IMPORTANT: Check 'Add Python to PATH' during installation." -ForegroundColor Yellow
        Pause-Exit 1
    }

    # Refresh PATH so the new install is visible in this session
    Refresh-Path

    Write-Step "Verifying Python installation..."
    $pythonCmd = Find-Python

    if (-not $pythonCmd) {
        Write-Fail "Python was installed but cannot be found in PATH."
        Write-Host "  Please close this window, open a new PowerShell, and run this script again." -ForegroundColor Yellow
        Pause-Exit 1
    }

    $verOutput = & $pythonCmd --version 2>&1
    Write-Ok "Verified: $verOutput"
}

# ---- Step 2: Install pip requirements ----------------------------------------
$reqFile = Join-Path $PSScriptRoot "requirements.txt"

if (Test-Path $reqFile) {
    Write-Step "Installing pip requirements..."
    try {
        & $pythonCmd -m pip install --quiet --upgrade pip 2>&1 | Out-Null
        & $pythonCmd -m pip install --quiet -r $reqFile 2>&1 | Out-Null
        Write-Ok "Requirements satisfied."
    }
    catch {
        Write-Fail "pip install encountered an issue: $_"
        Write-Host "  Continuing anyway (this project may not need external packages)." -ForegroundColor Yellow
    }
}
else {
    Write-Ok "No requirements.txt found - skipping pip install."
}

# ---- Step 3: Verify the GUI script exists ------------------------------------
$guiScript = Join-Path $PSScriptRoot "forgesteel_gui.py"

if (-not (Test-Path $guiScript)) {
    Write-Fail "Cannot find forgesteel_gui.py in $(Get-Location)"
    Write-Host "  Make sure this .ps1 file is in the same folder as forgesteel_gui.py" -ForegroundColor Yellow
    Pause-Exit 1
}

# ---- Step 4: Launch the GUI -------------------------------------------------
Write-Ok "Launching Forgesteel GUI..."
Write-Host ""

try {
    & $pythonCmd $guiScript
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "GUI exited with code $LASTEXITCODE."
        Pause-Exit $LASTEXITCODE
    }
}
catch {
    Write-Fail "Failed to launch GUI: $_"
    Pause-Exit 1
}

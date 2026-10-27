<#
  setup_artifacts.ps1 - puts the exported notebook files in D:\Nids_APP\artifacts (the folder the app reads).

  Run from the app folder:
      .\setup_artifacts.ps1                                  search your drives and install the best export found
      .\setup_artifacts.ps1 -Source "E:\path\nids_export.zip"        a specific zip,
      .\setup_artifacts.ps1 -Source "E:\path\nids_export"            an export folder,
      .\setup_artifacts.ps1 -Source "E:\GitHub\Network-Intrusion-Detection-System\models"   or a folder of model files
      add -Force to replace an existing installation

  All the logic lives in setup_artifacts.py (so it can be tested); this file only launches it.
  If PowerShell blocks the script:  Set-ExecutionPolicy -Scope Process Bypass
#>
param([string]$Source = "", [switch]$Force)
Set-Location $PSScriptRoot
$pyArgs = @("setup_artifacts.py")
if ($Source -ne "") { $pyArgs += @("--source", $Source) }
if ($Force) { $pyArgs += "--force" }
python @pyArgs
exit $LASTEXITCODE

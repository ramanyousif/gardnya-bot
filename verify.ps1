$source = [System.IO.File]::ReadAllText("$PSScriptRoot\bot.ps1")
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors) {
    $errors | ForEach-Object { Write-Host "Line $($_.Extent.StartLineNumber): $($_.Message)" }
    exit 1
}
Write-Host "POWERSHELL_SYNTAX_OK"

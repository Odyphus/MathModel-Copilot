param([Parameter(Mandatory=$true)][string]$InputDocx, [Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference = 'Stop'
$wordApp = $null
$document = $null
$ownedInstance = $false
try {
    if (Test-Path -LiteralPath $OutputPdf) { throw 'Output exists' }
    $wordApp = New-Object -ComObject Word.Application
    # Never close or hide an existing user's Word session.
    if ($wordApp.Visible -or $wordApp.Documents.Count -ne 0) { throw 'Word is in use' }
    $ownedInstance = $true
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $document = $wordApp.Documents.Open($InputDocx, $false, $true, $false)
    $document.ExportAsFixedFormat($OutputPdf, 17)
} finally {
    $saveChanges = 0
    if ($null -ne $document) { $document.Close([ref]$saveChanges) }
    if ($ownedInstance) { $wordApp.Quit([ref]$saveChanges) }
    if ($null -ne $document) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) }
    if ($null -ne $wordApp) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp) }
}

#Requires -Version 5.1

<#
.SYNOPSIS
Normalizes the Windows queue used for PLC parcel labels.

.DESCRIPTION
Keeps the Brother-specific "Thick" media setting, but makes A5, simplex and
native 100% scaling explicit. Run once on every Windows PC that uses the
"Paketmarke A5" queue.
#>

[CmdletBinding()]
param(
    [string]$Queue = "Paketmarke A5"
)

$ErrorActionPreference = "Stop"

$printer = Get-Printer -Name $Queue
if ($printer.JobCount -ne 0) {
    throw "Auf '$Queue' ist noch ein Druckauftrag aktiv. Einrichtung abgebrochen."
}

Set-PrintConfiguration `
    -PrinterName $Queue `
    -PaperSize A5 `
    -DuplexingMode OneSided `
    -Color $false

$configuration = Get-PrintConfiguration -PrinterName $Queue
[xml]$ticket = $configuration.PrintTicketXML
$namespaces = New-Object System.Xml.XmlNamespaceManager($ticket.NameTable)
$namespaces.AddNamespace(
    "psf",
    "http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework"
)

$media = $ticket.SelectSingleNode(
    "//psf:Feature[@name='psk:PageMediaType']/psf:Option",
    $namespaces
)
$scaling = $ticket.SelectSingleNode(
    "//psf:Feature[@name='psk:PageScaling']/psf:Option",
    $namespaces
)
if (-not $media -or $media.GetAttribute("name") -ne "brpsk:Thick") {
    throw "Die Medienart von '$Queue' ist nicht 'Dickes Papier' (brpsk:Thick)."
}
if (-not $scaling -or $scaling.GetAttribute("name") -ne "psk:None") {
    throw "Die Treiberskalierung von '$Queue' ist nicht ausgeschaltet."
}
if ($configuration.PaperSize -ne "A5" -or $configuration.DuplexingMode -ne "OneSided") {
    throw "Die Warteschlange '$Queue' konnte nicht als A5/einseitig verifiziert werden."
}

[pscustomobject]@{
    Queue = $Queue
    PhysicalPrinter = $printer.PortName
    Paper = $configuration.PaperSize
    Media = $media.GetAttribute("name")
    Duplex = $configuration.DuplexingMode
    Scaling = "100 % (keine Treiberskalierung)"
}

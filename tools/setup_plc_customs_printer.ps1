#Requires -Version 5.1

<#
.SYNOPSIS
Creates the dedicated XW-Office A5/100% customs printer queue.

.DESCRIPTION
The physical Brother printer and its driver/port are reused from the legacy
"Zollformular" queue. The legacy queue remains untouched at its own scaling.
The XW queue is configured for A5, label media, simplex, and no driver-side
page scaling. Run once on every Windows PC that prints PLC customs forms.
#>

[CmdletBinding()]
param(
    [string]$SourceQueue = "Zollformular",
    [string]$TargetQueue = "Zollformular XW 100"
)

$ErrorActionPreference = "Stop"

$source = Get-Printer -Name $SourceQueue
if ($source.JobCount -ne 0) {
    throw "Auf '$SourceQueue' ist noch ein Druckauftrag aktiv. Einrichtung abgebrochen."
}

$target = Get-Printer -Name $TargetQueue -ErrorAction SilentlyContinue
if (-not $target) {
    Add-Printer `
        -Name $TargetQueue `
        -DriverName $source.DriverName `
        -PortName $source.PortName `
        -Comment "XW-Office PLC-Zollformular: A5 Etikett, Skalierung 100 %"
}

Set-PrintConfiguration `
    -PrinterName $TargetQueue `
    -PaperSize A5 `
    -DuplexingMode OneSided `
    -Color $false

$configuration = Get-PrintConfiguration -PrinterName $TargetQueue
[xml]$ticket = $configuration.PrintTicketXML
$namespaces = New-Object System.Xml.XmlNamespaceManager($ticket.NameTable)
$namespaces.AddNamespace("psf", "http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework")

$media = $ticket.SelectSingleNode(
    "//psf:Feature[@name='psk:PageMediaType']/psf:Option",
    $namespaces
)
if (-not $media) {
    throw "Der Brother-Treiber stellt keine konfigurierbare Medienart bereit."
}
$media.SetAttribute("name", "psk:Label")

# A missing PageScaling feature means native 100%. Remove inherited custom
# scaling explicitly; the legacy queue may contain PageScalingScale=92.
$scalingNodes = $ticket.SelectNodes(
    "//psf:Feature[@name='psk:PageScaling'] | " +
    "//psf:ParameterInit[@name='psk:PageScalingScale'] | " +
    "//psf:Property[@name='brpsk:PageScalingData']",
    $namespaces
)
foreach ($node in @($scalingNodes)) {
    $node.ParentNode.RemoveChild($node) | Out-Null
}

Set-PrintConfiguration -PrinterName $TargetQueue -PrintTicketXml $ticket.OuterXml

$verified = Get-PrintConfiguration -PrinterName $TargetQueue
[xml]$verifiedTicket = $verified.PrintTicketXML
$verifiedNamespaces = New-Object System.Xml.XmlNamespaceManager($verifiedTicket.NameTable)
$verifiedNamespaces.AddNamespace(
    "psf",
    "http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework"
)
$verifiedMedia = $verifiedTicket.SelectSingleNode(
    "//psf:Feature[@name='psk:PageMediaType']/psf:Option",
    $verifiedNamespaces
)
$verifiedScale = $verifiedTicket.SelectSingleNode(
    "//psf:ParameterInit[@name='psk:PageScalingScale']/psf:Value",
    $verifiedNamespaces
)
$target = Get-Printer -Name $TargetQueue

if (
    $verified.PaperSize -ne "A5" -or
    $verified.DuplexingMode -ne "OneSided" -or
    $verifiedMedia.GetAttribute("name") -ne "psk:Label" -or
    $verifiedScale -or
    $target.DriverName -ne $source.DriverName -or
    $target.PortName -ne $source.PortName
) {
    throw "Die Warteschlange '$TargetQueue' konnte nicht als A5/Etikett/100% verifiziert werden."
}

[pscustomobject]@{
    Queue = $TargetQueue
    PhysicalPrinter = $target.PortName
    Paper = $verified.PaperSize
    Media = $verifiedMedia.GetAttribute("name")
    Duplex = $verified.DuplexingMode
    Scaling = "100 % (keine Treiberskalierung)"
}

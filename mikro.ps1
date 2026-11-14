# Mikrofone für ORB: listet aktive Aufnahmegeräte oder macht eins zum Windows-Standard
# (Spracherkennung im Fenster nutzt immer das Windows-Standardmikrofon).
#   mikro.ps1 -Liste            → JSON [{ id, name, standard }]
#   mikro.ps1 -Name "TONOR"     → erstes passendes Gerät als Standard (alle Rollen), Ausgabe: Gerätename oder leer
param([string]$Name = "", [switch]$Liste)
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
$geraete = @()
foreach ($k in Get-ChildItem $root) {
    if ((Get-ItemProperty $k.PSPath).DeviceState -ne 1) { continue }   # 1 = aktiv/angeschlossen
    $p = Get-ItemProperty (Join-Path $k.PSPath "Properties")
    $art = $p."{a45c254e-df1c-4efd-8020-67d146a850e0},2"; $teil = $p."{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
    $n = if ($teil) { "$art ($teil)" } else { "$art" }
    $geraete += [pscustomobject]@{ id = "{0.0.1.00000000}." + $k.PSChildName; name = $n }
}
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
[ComImport, Guid("F8679F50-850A-41cf-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IOrbPolicyConfig {
    int A(); int B(); int C(); int D(); int E(); int F(); int G(); int H(); int I(); int J();
    [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string id, int role);
}
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")] class OrbPolicyClient {}
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IOrbEnum { int X(); [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IOrbDevice d); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IOrbDevice { int X(); int Y(); [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class OrbEnumClient {}
public static class OrbMikro {
    public static string Standard() { IOrbDevice d; string id = "";
        if (((IOrbEnum)new OrbEnumClient()).GetDefaultAudioEndpoint(1, 0, out d) == 0) d.GetId(out id); return id; }
    public static int Setzen(string id) { var p = (IOrbPolicyConfig)new OrbPolicyClient(); int r = 0;
        for (int i = 0; i < 3; i++) r |= p.SetDefaultEndpoint(id, i); return r; }
}
"@
$std = ""; try { $std = [OrbMikro]::Standard() } catch {}
if ($Liste) {
    $l = @($geraete | ForEach-Object { [pscustomobject]@{ id = $_.id; name = $_.name; standard = ($_.id -eq $std) } })
    ConvertTo-Json -Compress -InputObject $l
    exit 0
}
if (-not $Name) { exit 0 }
$g = $geraete | Where-Object { $_.name -like "*$Name*" -or ($Name.Length -ge 12 -and $Name -like "*$($_.name)*") } | Select-Object -First 1
if (-not $g) { exit 1 }
if ($g.id -ne $std) { try { [void][OrbMikro]::Setzen($g.id) } catch { exit 2 } }
$g.name

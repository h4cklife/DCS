# Microphone diagnostic for ATCAI.
#
# Answers "is it hearing me at all?" by reporting, for a fixed number of seconds:
#   - which recording device Windows actually gave us
#   - the live input level
#   - the recogniser's own complaints (too soft, too loud, too noisy, no signal)
#   - everything it recognised, AND everything it rejected
#
# That last pair is the point. The recognition loop in recognize.ps1 is synchronous and
# returns null both for silence and for speech that matched no phrase, so a rejected
# utterance is invisible there. Here they are told apart, which is the difference
# between "the mic is dead" and "the mic is fine, the words didn't match".
#
# Deliberately separate from recognize.ps1: that path works and took a long time to get
# right, and a diagnostic must not be able to break it.
#
# Line protocol on stdout, same shape as recognize.ps1:
#   DEVICE|<name>   READY|<seconds>   LEVEL|<0-100>   STATE|<audio state>
#   PROBLEM|<name>  HEARD|<conf>|<text>  REJECTED|<conf>|<text>  DONE|  ERROR|<message>

param(
    [Parameter(Mandatory = $true)][string]$SpecFile,
    [int]$Seconds = 15,
    # List the active recording devices and exit, without holding the microphone.
    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"

function Write-Line($text) {
    Write-Output $text
    [Console]::Out.Flush()
}

try {
    Add-Type -AssemblyName System.Speech
} catch {
    Write-Line "ERROR|System.Speech unavailable: $($_.Exception.Message)"
    exit 1
}

# ---------- which microphone are we actually on ----------
# System.Speech binds to the Windows default recording device and never says which one
# that is. Core Audio is the only way to ask, so this is a small COM interop. It is
# best-effort: if it fails the test still runs, it just can't name the device.
function Get-DefaultCaptureDevice {
    try {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AtcaiMic {
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class Enumerator { }
    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceEnumerator {
        int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppEndpoint);
    }
    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceCollection {
        int GetCount(out int cDevices);
        int Item(int nDevice, out IMMDevice ppDevice);
    }
    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDevice {
        int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
        int OpenPropertyStore(int stgmAccess, out IPropertyStore ppProperties);
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string ppstrId);
        int GetState(out int pdwState);
    }
    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        int GetCount(out int cProps);
        int GetAt(int iProp, out PROPERTYKEY pkey);
        int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
    }
    [ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioMeterInformation { int GetPeakValue(out float peak); }
    [StructLayout(LayoutKind.Sequential)] struct PROPERTYKEY { public Guid fmtid; public int pid; }
    [StructLayout(LayoutKind.Explicit)] struct PROPVARIANT {
        [FieldOffset(0)] public short vt;
        [FieldOffset(8)] public IntPtr pointerValue;
    }
    static string NameOf(IMMDevice dev) {
        IPropertyStore store;
        if (dev.OpenPropertyStore(0, out store) != 0) return null;
        var key = new PROPERTYKEY();
        key.fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0");     // PKEY_Device_FriendlyName
        key.pid = 14;
        PROPVARIANT pv;
        if (store.GetValue(ref key, out pv) != 0) return null;
        return Marshal.PtrToStringUni(pv.pointerValue);
    }
    public static string Default() {
        var e = (IMMDeviceEnumerator)(new Enumerator());
        IMMDevice dev;
        if (e.GetDefaultAudioEndpoint(1, 0, out dev) != 0) return null;   // eCapture, eConsole
        return NameOf(dev);
    }
    // Active capture endpoints only. A machine can carry twenty of these - VR headsets,
    // webcams, unplugged jacks - and a list that long is worse than none. DEVICE_STATE
    // 0x1 is ACTIVE; disabled, unplugged and absent ones are left out.
    public static string[] Active() {
        var e = (IMMDeviceEnumerator)(new Enumerator());
        IMMDevice def = null;
        e.GetDefaultAudioEndpoint(1, 0, out def);
        string defId = null;
        if (def != null) def.GetId(out defId);

        IMMDeviceCollection col;
        if (e.EnumAudioEndpoints(1, 0x1, out col) != 0) return new string[0];
        int n;
        col.GetCount(out n);
        var rows = new System.Collections.Generic.List<string>();
        for (int i = 0; i < n; i++) {
            IMMDevice d;
            if (col.Item(i, out d) != 0) continue;
            string id;
            d.GetId(out id);
            string name = NameOf(d);
            if (name == null) continue;
            rows.Add(string.Format("{0}|{1}", (id == defId ? "1" : "0"), name));
        }
        return rows.ToArray();
    }
    // Live level per device, straight from the audio endpoint. Needs no capture session
    // of our own, which is why it can report on devices the recogniser isn't using.
    public static string[] Peaks() {
        var e = (IMMDeviceEnumerator)(new Enumerator());
        IMMDevice def = null;
        e.GetDefaultAudioEndpoint(1, 0, out def);
        string defId = null;
        if (def != null) def.GetId(out defId);

        IMMDeviceCollection col;
        if (e.EnumAudioEndpoints(1, 0x1, out col) != 0) return new string[0];
        int n;
        col.GetCount(out n);
        var rows = new System.Collections.Generic.List<string>();
        for (int i = 0; i < n; i++) {
            IMMDevice d;
            if (col.Item(i, out d) != 0) continue;
            string id;
            d.GetId(out id);
            string name = NameOf(d);
            if (name == null) continue;
            var iid = typeof(IAudioMeterInformation).GUID;
            object o;
            float peak = 0;
            if (d.Activate(ref iid, 0, IntPtr.Zero, out o) == 0) {
                ((IAudioMeterInformation)o).GetPeakValue(out peak);
            }
            rows.Add(string.Format("{0}|{1}|{2}", (id == defId ? "1" : "0"),
                (int)Math.Round(peak * 100), name));
        }
        return rows.ToArray();
    }
}
"@
        return [AtcaiMic]::Default()
    } catch {
        return $null
    }
}

function Get-ActiveCaptureDevices {
    try { return [AtcaiMic]::Active() } catch { return @() }
}

function Get-DevicePeaks {
    try { return [AtcaiMic]::Peaks() } catch { return @() }
}

# Highest level each device reached during the test, so a flat device in use can be
# reported alongside a live one that isn't.
$script:peakSeen = @{}
$script:peakIsDefault = @{}

function Sample-Peaks {
    foreach ($row in Get-DevicePeaks) {
        $parts = $row -split "\|", 3
        if ($parts.Count -lt 3) { continue }
        $name = $parts[2]
        $level = [int]$parts[1]
        if (-not $script:peakSeen.ContainsKey($name) -or $script:peakSeen[$name] -lt $level) {
            $script:peakSeen[$name] = $level
        }
        $script:peakIsDefault[$name] = ($parts[0] -eq "1")
    }
}

$device = Get-DefaultCaptureDevice
if ($device) {
    Write-Line "DEVICE|$device"
} else {
    Write-Line "DEVICE|(Windows default - name unavailable)"
}

# Which microphones Windows could have chosen. ATCAI can't pick one - System.Speech
# binds to whatever Windows says is default - so naming the alternatives is the only
# way a player can tell the wrong one is selected.
foreach ($row in Get-ActiveCaptureDevices) {
    Write-Line "INPUT|$row"
}

if ($ListOnly) {
    Write-Line "DONE|"
    exit 0
}

# ---------- the same grammar the real recogniser uses ----------
try {
    $spec = Get-Content -LiteralPath $SpecFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Line "ERROR|could not read phrase spec: $($_.Exception.Message)"
    exit 1
}

$phrases = @($spec.requests | ForEach-Object { "$_".Trim() } | Where-Object { $_ -ne "" })
if ($phrases.Count -eq 0) {
    Write-Line "ERROR|no request phrases supplied"
    exit 1
}

$requests = New-Object System.Speech.Recognition.Choices
foreach ($phrase in $phrases) { $requests.Add($phrase) }

function New-OptionalWildcard {
    $wild = New-Object System.Speech.Recognition.GrammarBuilder
    $wild.AppendWildcard()
    $choices = New-Object System.Speech.Recognition.Choices
    $choices.Add((New-Object System.Speech.Recognition.GrammarBuilder))
    $choices.Add($wild)
    return $choices
}

try {
    $builder = New-Object System.Speech.Recognition.GrammarBuilder
    if ($spec.wildcards) { $builder.Append((New-OptionalWildcard)) }
    $builder.Append($requests)
    if ($spec.wildcards) { $builder.Append((New-OptionalWildcard)) }
    $grammar = New-Object System.Speech.Recognition.Grammar($builder)
} catch {
    Write-Line "ERROR|could not build grammar: $($_.Exception.Message)"
    exit 1
}

try {
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $engine.SetInputToDefaultAudioDevice()
    $engine.LoadGrammar($grammar)
} catch {
    Write-Line "ERROR|could not open the microphone: $($_.Exception.Message)"
    exit 1
}

# Events rather than the synchronous Recognize() loop: levels and rejections are only
# available as events. Registered without -Action so they surface on this thread, where
# Write-Output actually reaches the pipe.
$null = Register-ObjectEvent -InputObject $engine -EventName SpeechRecognized -SourceIdentifier MicHeard
$null = Register-ObjectEvent -InputObject $engine -EventName SpeechRecognitionRejected -SourceIdentifier MicRejected
$null = Register-ObjectEvent -InputObject $engine -EventName AudioLevelUpdated -SourceIdentifier MicLevel
$null = Register-ObjectEvent -InputObject $engine -EventName AudioSignalProblemOccurred -SourceIdentifier MicProblem
$null = Register-ObjectEvent -InputObject $engine -EventName AudioStateChanged -SourceIdentifier MicState

try {
    $engine.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
} catch {
    Write-Line "ERROR|could not start recognition: $($_.Exception.Message)"
    exit 1
}

Write-Line "READY|$Seconds"

$deadline = (Get-Date).AddSeconds($Seconds)
$lastLevel = -1
$lastLevelAt = [DateTime]::MinValue

while ((Get-Date) -lt $deadline) {
    Sample-Peaks
    $ev = Wait-Event -Timeout 1
    if ($null -eq $ev) { continue }

    switch ($ev.SourceIdentifier) {
        "MicHeard" {
            $r = $ev.SourceEventArgs.Result
            Write-Line ("HEARD|{0:F2}|{1}" -f $r.Confidence, $r.Text)
        }
        "MicRejected" {
            $r = $ev.SourceEventArgs.Result
            if ($null -ne $r) {
                Write-Line ("REJECTED|{0:F2}|{1}" -f $r.Confidence, $r.Text)
            } else {
                Write-Line "REJECTED|0.00|"
            }
        }
        "MicLevel" {
            # Fires many times a second; throttled so the panel isn't flooded.
            $level = [int]$ev.SourceEventArgs.AudioLevel
            $now = Get-Date
            if ($level -ne $lastLevel -and ($now - $lastLevelAt).TotalMilliseconds -ge 100) {
                Write-Line "LEVEL|$level"
                $lastLevel = $level
                $lastLevelAt = $now
            }
        }
        "MicProblem" {
            Write-Line ("PROBLEM|{0}" -f $ev.SourceEventArgs.AudioSignalProblem)
        }
        "MicState" {
            Write-Line ("STATE|{0}" -f $ev.SourceEventArgs.AudioState)
        }
    }
    Remove-Event -EventIdentifier $ev.EventIdentifier
}

try { $engine.RecognizeAsyncStop() } catch { }
Unregister-Event -SourceIdentifier MicHeard -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier MicRejected -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier MicLevel -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier MicProblem -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier MicState -ErrorAction SilentlyContinue
try { $engine.Dispose() } catch { }

# What each microphone actually produced, measured at the device rather than inferred
# from what the recogniser made of it.
foreach ($name in $script:peakSeen.Keys) {
    $flag = if ($script:peakIsDefault[$name]) { "1" } else { "0" }
    Write-Line ("SIGNAL|$flag|" + $script:peakSeen[$name] + "|$name")
}

Write-Line "DONE|"

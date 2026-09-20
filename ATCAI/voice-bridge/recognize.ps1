# Offline speech recognition for ATCAI, using the recogniser built into Windows.
#
# Builds a grammar of ATC request phrases, optionally padded with wildcards so the
# request can be surrounded by anything else you say — a callsign, the tower's name,
# a runway, "over". Without the wildcards the recogniser has to match your whole
# utterance exactly, which makes realistic radio calls impossible.
#
# Prints each match to stdout as "confidence|text".
# Driven by atcai_listen.py — run that rather than this directly.

param(
    [Parameter(Mandatory = $true)][string]$SpecFile
)

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Speech
} catch {
    Write-Output "ERROR|System.Speech unavailable: $($_.Exception.Message)"
    exit 1
}

try {
    $spec = Get-Content -LiteralPath $SpecFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Output "ERROR|could not read phrase spec: $($_.Exception.Message)"
    exit 1
}

$phrases = @($spec.requests | ForEach-Object { "$_".Trim() } | Where-Object { $_ -ne "" })
if ($phrases.Count -eq 0) {
    Write-Output "ERROR|no request phrases supplied"
    exit 1
}

$requests = New-Object System.Speech.Recognition.Choices
foreach ($phrase in $phrases) { $requests.Add($phrase) }

# An empty alternative alongside a wildcard makes the surrounding speech optional:
# the request can stand alone, or be embedded in a longer transmission.
function New-OptionalWildcard {
    $wild = New-Object System.Speech.Recognition.GrammarBuilder
    $wild.AppendWildcard()
    $choices = New-Object System.Speech.Recognition.Choices
    $choices.Add((New-Object System.Speech.Recognition.GrammarBuilder))
    $choices.Add($wild)
    return $choices
}

$builder = New-Object System.Speech.Recognition.GrammarBuilder
try {
    if ($spec.wildcards) { $builder.Append((New-OptionalWildcard)) }
    $builder.Append($requests)
    if ($spec.wildcards) { $builder.Append((New-OptionalWildcard)) }
    $grammar = New-Object System.Speech.Recognition.Grammar($builder)
} catch {
    Write-Output "ERROR|could not build grammar: $($_.Exception.Message)"
    exit 1
}

try {
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $engine.SetInputToDefaultAudioDevice()
    $engine.LoadGrammar($grammar)
} catch {
    Write-Output "ERROR|could not open the microphone: $($_.Exception.Message)"
    exit 1
}

$mode = if ($spec.wildcards) { "flexible" } else { "strict" }
Write-Output "READY|$($phrases.Count) phrases, $mode matching"
[Console]::Out.Flush()

# Synchronous recognition in a loop: simpler and more predictable to drive from a pipe
# than the async event model, and the timeout keeps it responsive to being killed.
while ($true) {
    $result = $engine.Recognize([TimeSpan]::FromSeconds(5))
    if ($null -ne $result) {
        Write-Output ("{0:F2}|{1}" -f $result.Confidence, $result.Text)
        [Console]::Out.Flush()
    }
}

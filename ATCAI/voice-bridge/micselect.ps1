# Choose which microphone ATCAI listens to.
#
# System.Speech offers no way to pick a device - it opens whatever SAPI's default audio
# input points at. That token is writable without elevation, and verified 2026-10-25 to
# be what System.Speech actually honours: pinning it to each of three devices in turn
# made the engine open exactly that device each time, confirmed through Core Audio's
# session API rather than inferred.
#
# Setting it affects speech applications only. Windows' own default recording device is
# untouched, so Discord, SRS and everything else carry on as before.
#
#   -List                      WINDOWS_DEFAULT|<description> then INPUT|<id>|<description>
#   -Set <token id>            pin ATCAI's microphone
#   -UseWindowsDefault         follow whatever Windows picks, as before
#
# Output: OK|<message> or ERROR|<message>.

param(
    [switch]$List,
    [string]$Set,
    [switch]$UseWindowsDefault
)

$ErrorActionPreference = "Stop"

# The category's own enumerator token, with no device GUID after it, means "whatever
# Windows says is default". That is what a stock machine has, and what restores it.
# Named _ID because PowerShell variable names are case-insensitive: a local $category
# would otherwise shadow a constant called $CATEGORY, and the COM object ends up being
# passed as its own id - which fails as an opaque HRESULT.
$CATEGORY_ID = "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\AudioInput"
$FOLLOW_WINDOWS_ID = "$CATEGORY_ID\TokenEnums\MMAudioIn\"

function Write-Line($text) {
    Write-Output $text
    [Console]::Out.Flush()
}

function Get-Category {
    $category = New-Object -ComObject SAPI.SpObjectTokenCategory
    $category.SetId($CATEGORY_ID, $false)
    return $category
}

function Describe-Token($id) {
    try {
        $token = New-Object -ComObject SAPI.SpObjectToken
        $token.SetId($id)
        return $token.GetDescription()
    } catch {
        return $null
    }
}

try {
    if ($List) {
        $category = Get-Category
        $current = $category.Default

        if ($current -eq $FOLLOW_WINDOWS_ID -or [string]::IsNullOrEmpty($current)) {
            Write-Line "CURRENT|windows-default"
        } else {
            Write-Line ("CURRENT|" + $current)
        }

        # What "follow Windows" currently resolves to, so the choice is informed.
        $resolved = Describe-Token $FOLLOW_WINDOWS_ID
        if ($resolved) { Write-Line ("WINDOWS_DEFAULT|" + $resolved) }

        $recognizer = New-Object -ComObject SAPI.SpInprocRecognizer
        foreach ($token in $recognizer.GetAudioInputs()) {
            Write-Line ("INPUT|" + $token.Id + "|" + $token.GetDescription())
        }
        Write-Line "OK|listed"
        exit 0
    }

    if ($UseWindowsDefault) {
        $category = Get-Category
        $category.Default = $FOLLOW_WINDOWS_ID
        Write-Line "OK|following the Windows default recording device again"
        exit 0
    }

    if ($Set) {
        # Checked against the real list rather than written blind: SAPI silently
        # substitutes a different device for an id it doesn't recognise, which would
        # look like success while selecting something else entirely.
        $recognizer = New-Object -ComObject SAPI.SpInprocRecognizer
        $match = $recognizer.GetAudioInputs() | Where-Object { $_.Id -eq $Set } |
                 Select-Object -First 1
        if (-not $match) {
            Write-Line "ERROR|that microphone is not available"
            exit 1
        }

        $category = Get-Category
        $category.Default = $Set

        # And read back, for the same reason.
        $check = Get-Category
        if ($check.Default -ne $Set) {
            Write-Line ("ERROR|Windows did not keep that choice (it reports " +
                        $check.Default + ")")
            exit 1
        }
        Write-Line ("OK|" + $match.GetDescription())
        exit 0
    }

    Write-Line "ERROR|nothing to do - pass -List, -Set or -UseWindowsDefault"
    exit 1
} catch {
    Write-Line ("ERROR|" + $_.Exception.Message)
    exit 1
}

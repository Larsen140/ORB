param([string]$In, [string]$Out)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'de-DE' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = 1
$s.SetOutputToWaveFile($Out)
$s.Speak([IO.File]::ReadAllText($In, [Text.Encoding]::UTF8))
$s.Dispose()

# Start Google Chrome with remote debugging so the agent can attach to YOUR session.
# Chrome 136+ ignores --remote-debugging-port on the default profile, so we use a
# dedicated profile folder: log in to ChatGPT (and your test blog) once there; it persists.
param(
  [string]$ProfileDir = "$env:LOCALAPPDATA\ResearchBlogAgent\ChromeProfile",
  [int]$Port = 9222
)
$candidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "Google Chrome not found." }
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
Start-Process -FilePath $chrome -ArgumentList @(
  "--remote-debugging-port=$Port", "--user-data-dir=`"$ProfileDir`"", "https://chatgpt.com/"
)
Write-Host "Chrome started on port $Port with profile $ProfileDir"

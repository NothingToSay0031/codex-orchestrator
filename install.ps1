param(
  [ValidateSet("global", "project")]
  [string]$Scope = "global",
  [string]$ProjectDir = ""
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPy = Join-Path $ScriptDir "install.py"

$PythonArgs = @($InstallPy)
if ($Scope -eq "project") { $PythonArgs += "--project" }
if ($ProjectDir) { $PythonArgs += "--project-dir=$ProjectDir" }

& python $PythonArgs
exit $LASTEXITCODE

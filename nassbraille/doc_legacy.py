"""Convert old Word files (.doc), RTF and ODT to .docx so read_docx can read them.

1. Microsoft Word through COM, driven by a PowerShell script:
   Documents.Open(ReadOnly, no conversion dialog) -> SaveAs2(FileFormat=16) ->
   Close(0) -> Quit. Paths travel as base64 UTF-16 in environment variables, so
   Arabic letters and spaces in folder names are never quoted into the script.
2. LibreOffice (soffice --headless --convert-to docx), if it is installed.
3. Otherwise ConversionError with an Arabic message.

The source is first copied into a fresh temp folder under an ASCII name; the
.docx is written next to it and the folder is removed when the program exits.
"""
from __future__ import annotations

import atexit
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .convert import ConversionError

WORD_TIMEOUT = 240          # seconds for opening + saving one document in Word
SOFFICE_TIMEOUT = 240

MSG_FAILED = ("مش قادر أحوّل الملف ده لصيغة docx. افتحه في Word واختار "
              "\"حفظ باسم\" (Save As) بصيغة \"مستند Word (*.docx)\" وبعدين افتح الملف الجديد.")
MSG_MISSING = "الملف مش موجود: {path}"

# Late-bound IDispatch calls with named arguments: PowerShell's own COM binder
# insists on [ref] for Word's optional VARIANT* parameters.
_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Decode([string]$b64) { [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($b64)) }
function Call($target, [string]$name, $named) {
    # no pipeline here: PowerShell would enumerate COM collections such as Documents
    $names = [string[]]@($named.Keys)
    $values = New-Object 'object[]' $named.Count
    $i = 0
    foreach ($v in $named.Values) {
        if ($null -ne $v) { $v = ([psobject]$v).psobject.BaseObject }
        $values[$i] = $v
        $i++
    }
    $result = [System.__ComObject].InvokeMember($name, [Reflection.BindingFlags]::InvokeMethod,
        $null, ([psobject]$target).psobject.BaseObject, $values, $null, $null, $names)
    return ,$result
}
[string]$src = Decode $env:NASSBRAILLE_SRC
[string]$dst = Decode $env:NASSBRAILLE_DST
[string]$pidFile = Decode $env:NASSBRAILLE_PIDFILE
$before = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$word = $null
$doc = $null
$shared = $false
$alerts = $null
$security = $null
try {
    $word = New-Object -ComObject Word.Application
    $mine = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue |
              Where-Object { $before -notcontains $_.Id } | ForEach-Object { $_.Id })
    if ($mine.Count -eq 1) { [IO.File]::WriteAllText($pidFile, [string]$mine[0]) }
    # a Word the user already works in is left open and as it was
    $shared = ($word.Documents.Count -gt 0)
    if (-not $shared) { $word.Visible = $false }
    $alerts = $word.DisplayAlerts
    $word.DisplayAlerts = 0
    try { $security = $word.AutomationSecurity; $word.AutomationSecurity = 3 } catch { }
    $open = [ordered]@{
        FileName = $src; ConfirmConversions = $false; ReadOnly = $true;
        AddToRecentFiles = $false; PasswordDocument = 'nassbraille-no-password';
        Visible = $false; NoEncodingDialog = $true
    }
    $documents = $word.Documents
    $doc = Call $documents 'Open' $open
    Call $doc 'SaveAs2' ([ordered]@{ FileName = $dst; FileFormat = 16 }) | Out-Null
    Call $doc 'Close' ([ordered]@{ SaveChanges = 0 }) | Out-Null
    $doc = $null
    Write-Output 'NASSBRAILLE-OK'
}
finally {
    if ($doc -ne $null) { try { Call $doc 'Close' ([ordered]@{ SaveChanges = 0 }) | Out-Null } catch { } }
    if ($word -ne $null) {
        if ($shared) {
            try { if ($alerts -ne $null) { $word.DisplayAlerts = $alerts } } catch { }
            try { if ($security -ne $null) { $word.AutomationSecurity = $security } } catch { }
        }
        else { try { Call $word 'Quit' ([ordered]@{ SaveChanges = 0 }) | Out-Null } catch { } }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch { }
    }
}
"""


def _b64(text):
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell():
    found = shutil.which("powershell") or shutil.which("powershell.exe")
    if found:
        return found
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else None


def word_available():
    """True when Word's COM class is registered (Windows only)."""
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


def _kill(pid_file):
    """Stop the Word process this conversion started (after a timeout)."""
    try:
        pid = int(Path(pid_file).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=_no_window(), timeout=30, check=False)


def _convert_with_word(src, dst, work):
    shell = _powershell()
    if shell is None or not word_available():
        raise RuntimeError("Word COM is not available")
    pid_file = work / "word.pid"
    env = dict(os.environ)
    env.update(NASSBRAILLE_SRC=_b64(str(src)), NASSBRAILLE_DST=_b64(str(dst)),
               NASSBRAILLE_PIDFILE=_b64(str(pid_file)))
    cmd = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-EncodedCommand", _b64(_PS_SCRIPT)]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=WORD_TIMEOUT,
                              creationflags=_no_window(), check=False)
    except subprocess.TimeoutExpired:
        _kill(pid_file)
        raise RuntimeError("Word did not finish in time")
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0 or "NASSBRAILLE-OK" not in out:
        raise RuntimeError("Word conversion failed: " + out.strip()[-500:])


def _find_soffice():
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.exists():
                return str(candidate)
    return None


def _convert_with_libreoffice(src, dst, work):
    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError("LibreOffice is not installed")
    profile = (work / "lo-profile").resolve().as_uri()
    cmd = [soffice, "-env:UserInstallation=" + profile, "--headless", "--norestore",
           "--convert-to", "docx", "--outdir", str(work), str(src)]
    subprocess.run(cmd, capture_output=True, timeout=SOFFICE_TIMEOUT,
                   creationflags=_no_window(), check=False)
    produced = work / (src.stem + ".docx")
    if produced != dst and produced.exists():
        produced.replace(dst)
    if not dst.exists():
        raise RuntimeError("LibreOffice did not produce a .docx")


def _content_suffix(path):
    """The extension that matches the file's content (Word trusts extensions)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        head = b""
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return ".doc"
    if head.startswith(b"{\\rtf"):
        return ".rtf"
    return path.suffix.lower() or ".doc"


def convert_to_docx(path):
    """Convert a .doc / .rtf / .odt file; returns the Path of a temporary .docx."""
    path = Path(path)
    if not path.is_file():
        raise ConversionError(MSG_MISSING.format(path=path))
    work = Path(tempfile.mkdtemp(prefix="nassbraille_"))
    atexit.register(shutil.rmtree, work, True)
    src = work / ("source" + _content_suffix(path))
    shutil.copyfile(path, src)
    dst = work / "converted.docx"
    for convert in (_convert_with_word, _convert_with_libreoffice):
        try:
            convert(src, dst, work)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            continue
        if dst.exists() and dst.stat().st_size > 0:
            return dst
    raise ConversionError(MSG_FAILED)

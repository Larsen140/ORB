Rem Startet tastatur.ps1 -Auftrag ganz ohne sichtbares Fenster (fuer die Aufgabe "ORB Tastatur")
Dim d : d = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & d & "\tastatur.ps1"" -Auftrag", 0, False

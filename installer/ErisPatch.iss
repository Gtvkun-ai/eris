[Setup]
AppName=Eris Patch Update
AppVersion=0.14.1
DefaultDirName={localappdata}\Programs\Eris
PrivilegesRequired=lowest
OutputDir=C:\Users\Gtvkun\Documents\eris_dist
OutputBaseFilename=ErisPatch
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyMemo=yes

[Files]
Source: "C:\Users\Gtvkun\Documents\eris\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "C:\Users\Gtvkun\Documents\eris\run_eris.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Run]
Filename: "{app}\run_eris.bat"; Description: "Khoi dong lai Eris ngay sau khi cap nhat"; Flags: postinstall runascurrentuser shellexec unchecked

[Setup]
AppName=Eris Patch Update
AppVersion=0.14.1
DefaultDirName={localappdata}\Programs\Eris
PrivilegesRequired=lowest
OutputDir=C:\Users\Gtvkun\Documents\eris_dist
#ifndef SourceDir
#define SourceDir "C:\Users\Gtvkun\Documents\eris_release"
#endif
#ifndef SetupOutputBaseFilename
#define SetupOutputBaseFilename "ErisPatch"
#endif
OutputBaseFilename={#SetupOutputBaseFilename}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyMemo=yes

[Files]
Source: "{#SourceDir}\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.sqlite,*.sqlite3,*.bak,__pycache__\*"
Source: "{#SourceDir}\run_eris.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Run]
Filename: "{app}\run_eris.bat"; Description: "Khoi dong lai Eris ngay sau khi cap nhat"; Flags: postinstall runascurrentuser shellexec unchecked

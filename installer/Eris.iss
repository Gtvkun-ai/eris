[Setup]
AppName=Eris
AppVersion=0.14.0
DefaultDirName={localappdata}\Programs\Eris
PrivilegesRequired=lowest
OutputDir=C:\Users\Gtvkun\Documents\eris_dist
#ifndef SourceDir
#define SourceDir "C:\Users\Gtvkun\Documents\eris_release"
#endif
#ifndef SetupOutputBaseFilename
#define SetupOutputBaseFilename "ErisSetup"
#endif
OutputBaseFilename={#SetupOutputBaseFilename}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".env,config\secrets.json,config\*.db,*.db,*.sqlite,*.sqlite3,logs\*,.cache\*,.eris_home\*,.eris_state\*,*.bak"

[Icons]
Name: "{autoprograms}\Eris Launcher"; Filename: "{app}\run_eris.bat"
Name: "{autodesktop}\Eris Launcher"; Filename: "{app}\run_eris.bat"
Name: "{autoprograms}\Eris Manager"; Filename: "{app}\ErisManager.exe"
Name: "{autodesktop}\Eris Manager"; Filename: "{app}\ErisManager.exe"

[Run]
Filename: "{app}\ErisManager.exe"; Description: "Mo bang quan ly tai khoan (Eris Manager)"; Flags: postinstall runascurrentuser skipifsilent

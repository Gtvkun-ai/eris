[Setup]
AppName=Eris
AppVersion=0.14.0
DefaultDirName={localappdata}\Programs\Eris
PrivilegesRequired=lowest
OutputDir=C:\Users\Gtvkun\Documents\eris_dist
OutputBaseFilename=ErisSetup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "C:\Users\Gtvkun\Documents\eris\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Eris Launcher"; Filename: "{app}\run_eris.bat"
Name: "{autodesktop}\Eris Launcher"; Filename: "{app}\run_eris.bat"
Name: "{autoprograms}\Eris Manager"; Filename: "{app}\python\python.exe"; Parameters: """{app}\eris_setup.py"""
Name: "{autodesktop}\Eris Manager"; Filename: "{app}\python\python.exe"; Parameters: """{app}\eris_setup.py"""

[Run]
Filename: "{app}\python\python.exe"; Parameters: """{app}\eris_setup.py"""; Description: "Mo bang quan ly tai khoan (Eris Manager)"; Flags: postinstall runascurrentuser

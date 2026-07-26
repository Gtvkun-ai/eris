$s = New-Object -ComObject WScript.Shell
$shortcut = $s.CreateShortcut("C:\Users\Gtvkun\Desktop\Godot_v4.6.2-stable_mono_win64 - Shortcut.lnk")
Write-Output $shortcut.TargetPath

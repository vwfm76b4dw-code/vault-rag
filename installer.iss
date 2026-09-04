; vault-rag 安装包脚本 — Inno Setup 6
; 构建: ISCC.exe installer.iss  →  dist/vault-rag-v1.2.2-setup.exe

#define MyAppName "vault-rag"
#define MyAppVersion "1.2.2"
#define MyAppPublisher "vault-rag"
#define MyAppExeName "vault-rag.exe"

[Setup]
AppId={{8E7B6C52-9A44-4E1D-9B7F-5A2C3D4E5F60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=vault-rag-v{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=vault-rag.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 (&D)"; \
  GroupDescription: "附加任务："

[Files]
Source: "dist\vault-rag\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理运行期在安装目录内产生的日志/临时文件（用户数据目录不在安装目录，不受影响）
Type: filesandordirs; Name: "{app}\data\uploads"
Type: filesandordirs; Name: "{app}\data\gguf"

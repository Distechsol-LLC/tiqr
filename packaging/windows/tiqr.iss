; TiQR Windows installer (Inno Setup 6.2 or newer, Unicode).
;
; Collects the settings of tiqr_brand.jsonc in a wizard and writes that file, and a copy of the
; chosen logo, into the install folder. Compile after assembling the bundle (see the release
; workflow), from the repository root:
;   iscc /DBundleDir=bundle\tiqr-Windows-X64 /DAppVersion=1.2.3 packaging\windows\tiqr.iss
;
; The schema, defaults and validation rules mirror apps/core/src/tiqr/core/settings.py,
; apps/api/src/tiqr/api/config.py and the committed tiqr_brand.jsonc. See ASSUMPTIONS.md.
; tests/test_windows_installer.py keeps the lists below in step with the app.

#define AppName "TiQR"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\..\bundle\tiqr-Windows-X64"
#endif
#define SkeletonThemesUrl "https://skeleton.dev/docs/svelte/design/themes"

[Setup]
AppId={{0C70AC7B-EF86-4DD2-9776-791215A62B49}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\TiQR
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; The program being installed is tiqr.exe, so the installer uses a different name.
OutputBaseFilename=tiqr_setup
OutputDir=..\..\release
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"


[Files]
; The bundle without its sample branding and the scripts the installer replaces.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "tiqr_brand.jsonc,install.cmd,install.sh"; Flags: ignoreversion recursesubdirs
; Both files below are prepared in PrepareToInstall; Setup copies them, so a cancelled install
; rolls them back and the uninstaller removes them.
Source: "{tmp}\tiqr_brand.jsonc"; DestDir: "{app}"; Flags: external ignoreversion
Source: "{code:LogoStagedPath}"; DestName: "{code:LogoFileName}"; DestDir: "{app}"; Flags: external ignoreversion; Check: LogoChosen
; The app resolves logo_path against its data folder, so the logo is also copied there.
Source: "{code:LogoStagedPath}"; DestName: "{code:LogoFileName}"; DestDir: "{commonappdata}\TiQR"; Flags: external ignoreversion; Check: LogoChosen
; Read by the wizard only.
Source: "timezones.txt"; DestDir: "{tmp}"; Flags: dontcopy


[UninstallDelete]
; The generated files (also in the uninstall log), the backup of an earlier file, and the logo
; under any extension. The user's original image is never in this list.
Type: files; Name: "{app}\tiqr_brand.jsonc"
Type: files; Name: "{app}\tiqr_brand.jsonc.bak"
Type: files; Name: "{app}\logo.png"
Type: files; Name: "{app}\logo.svg"
Type: files; Name: "{app}\logo.jpg"
Type: files; Name: "{app}\logo.jpeg"
Type: files; Name: "{commonappdata}\TiQR\tiqr_brand.jsonc"
Type: files; Name: "{commonappdata}\TiQR\tiqr_brand.jsonc.bak"
Type: files; Name: "{commonappdata}\TiQR\logo.png"
Type: files; Name: "{commonappdata}\TiQR\logo.svg"
Type: files; Name: "{commonappdata}\TiQR\logo.jpg"
Type: files; Name: "{commonappdata}\TiQR\logo.jpeg"

[Code]
const
  NL = #13#10;
  SkeletonThemesUrl = '{#SkeletonThemesUrl}';
  BrandFile = 'tiqr_brand.jsonc';

  { Every theme the web app imports (apps/web/src/data/themes.ts). "vintage" is written as "default". }
  ThemeNames = 'catppuccin|cerberus|concord|crimson|dracula|fennec|hamlindigo|legacy|mint|modern|mona|nosh|nouveau|pine|reign|rocket|rose|rosepine|sahara|seafoam|terminus|vintage|vox|wintry';
  DefaultThemeName = 'vintage';
  DefaultThemeValue = 'default';

  { The app is translated into these; the region only picks the flag (core/languages.py). }
  LanguageCodes = 'en-US|ru-RU|az-AZ|kk-KZ';
  LanguageLabels = 'English (en-US)|Russian (ru-RU)|Azerbaijani (az-AZ)|Kazakh (kk-KZ)';
  DefaultLanguages = 'en-US|ru-RU|az-AZ';

  { The currencies a price may be in, chosen apart from the languages (core/models.py Currency). }
  CurrencyCodes = 'USD|RUB|AZN|KZT';
  CurrencyLabels = 'US dollar (USD)|Russian ruble (RUB)|Azerbaijani manat (AZN)|Kazakhstani tenge (KZT)';
  DefaultCurrencies = 'USD|RUB|AZN';

  { Defaults the constructor documents; they pre-fill the pages. }
  DefaultPrefix = 'TQR';
  DefaultHost = '127.0.0.1';
  DefaultPort = '7102';
  DefaultBioTimeout = '30';
  DefaultBioDoorDuration = '3';
  DefaultBioDoorTimeout = '10';

  LogoExtensions = '.png|.svg|.jpg|.jpeg';
  LogoMaxBytes = 20971520;

type
  { Everything tiqr_brand.jsonc holds, as the user typed it. Empty text means null (key left to the
    lower layers); it is the only thing BuildBrandJsonc reads. LogoSource is install-only: the file
    to copy, never written to the JSON. }
  TBrand = record
    AppName: String;
    LogoSource: String;
    LogoFile: String;
    Theme: String;
    Languages: String;
    Currencies: String;
    Prefix: String;
    TimeZone: String;
    Host: String;
    Port: String;
    TlsOn: Boolean;
    TlsCert: String;
    TlsKey: String;
    ServerPrinting: Boolean;
  end;

var
  { The wizard pages, in the order the user sees them. Each page groups related settings. }
  AppPage: TWizardPage;
  AppNameEdit: TNewEdit;
  LogoEdit: TNewEdit;
  PrefixEdit: TNewEdit;
  ThemeCombo: TNewComboBox;
  RegionPage: TWizardPage;
  TimeZoneEdit: TNewEdit;
  LanguageList: TNewCheckListBox;
  CurrencyList: TNewCheckListBox;
  NetworkPage: TInputQueryWizardPage;
  PassWebhookPage: TInputQueryWizardPage;
  SecurityPage: TInputOptionWizardPage;
  TlsFilesPage: TInputFileWizardPage;

  KnownTimeZones: String;
  Reinstalling: Boolean;
  Updating: Boolean;

{ ---------------------------------------------------------------------------------------------
  Text helpers
  --------------------------------------------------------------------------------------------- }

function SplitText(const Text: String; Separator: Char): TArrayOfString;
var
  I, Count: Integer;
  Part: String;
begin
  Count := 0;
  Part := '';
  SetArrayLength(Result, 0);
  for I := 1 to Length(Text) do
  begin
    if Text[I] = Separator then
    begin
      SetArrayLength(Result, Count + 1);
      Result[Count] := Part;
      Count := Count + 1;
      Part := '';
    end
    else
      Part := Part + Text[I];
  end;
  SetArrayLength(Result, Count + 1);
  Result[Count] := Part;
end;

function IsDigits(const Text: String): Boolean;
var
  I: Integer;
begin
  Result := Text <> '';
  for I := 1 to Length(Text) do
    if (Text[I] < '0') or (Text[I] > '9') then
      Result := False;
end;

function IsWholeNumber(const Text: String): Boolean;
begin
  { Nine digits fit an Integer and are far beyond any sensible port or interval. }
  Result := IsDigits(Text) and (Length(Text) <= 9);
end;

{ ---------------------------------------------------------------------------------------------
  Validators: each returns an error message, or '' when the value is fine. The wizard runs them
  as the user leaves a page; PrepareToInstall runs them all again before anything is written.
  --------------------------------------------------------------------------------------------- }

function ValidateAppName(const B: TBrand): String;
begin
  Result := '';
  if B.AppName = '' then
    Result := 'Enter an app name. It is required.';
end;

function HasImageSignature(const Content: AnsiString; const Extension: String): Boolean;
begin
  Result := False;
  if Length(Content) < 4 then
    Exit;
  if (Extension = '.png') then
    Result := (Ord(Content[1]) = $89) and (Copy(Content, 2, 3) = 'PNG')
  else if (Extension = '.jpg') or (Extension = '.jpeg') then
    Result := (Ord(Content[1]) = $FF) and (Ord(Content[2]) = $D8) and (Ord(Content[3]) = $FF)
  else if Extension = '.svg' then
    Result := Pos('<svg', Copy(Content, 1, 65536)) > 0;
end;

{ The extension must be one the app serves (core's LOGO_SUFFIXES) and the content must match it, so
  a renamed document is not copied in as a logo. }
function ValidateLogo(const B: TBrand): String;
var
  Extension: String;
  Size: Integer;
  Content: AnsiString;
begin
  Result := '';
  if B.LogoSource = '' then
    Exit;
  Extension := Lowercase(ExtractFileExt(B.LogoSource));
  if Pos('|' + Extension + '|', '|' + LogoExtensions + '|') = 0 then
    Result := 'The logo must be a PNG, SVG or JPG image (.png, .svg, .jpg or .jpeg).'
  else if not FileExists(B.LogoSource) then
    Result := 'The logo file was not found:' + NL + B.LogoSource
  else if not FileSize(B.LogoSource, Size) or (Size <= 0) or (Size > LogoMaxBytes) then
    Result := 'The logo must be a file of up to 20 MB:' + NL + B.LogoSource
  else if not LoadStringFromFile(B.LogoSource, Content) then
    Result := 'The logo file could not be read:' + NL + B.LogoSource
  else if not HasImageSignature(Content, Extension) then
    Result := 'The file is not a valid ' + Uppercase(Copy(Extension, 2, Length(Extension))) + ' image:' + NL + B.LogoSource;
end;

function ValidateTheme(const B: TBrand): String;
begin
  Result := '';
  if B.Theme = '' then
    Result := 'Choose a theme.';
end;

function ValidateLanguages(const B: TBrand): String;
begin
  Result := '';
  if B.Languages = '' then
    Result := 'Choose at least one language.';
end;

function ValidateCurrencies(const B: TBrand): String;
begin
  Result := '';
  if B.Currencies = '' then
    Result := 'Choose at least one currency.';
end;

{ Exactly three printable ASCII characters, none of ":" or "-" (core's validate_prefix). Blank keeps
  the default. }
function ValidatePrefix(const B: TBrand): String;
var
  I: Integer;
  Bad: Boolean;
begin
  Result := '';
  if B.Prefix = '' then
    Exit;
  Bad := Length(B.Prefix) <> 3;
  for I := 1 to Length(B.Prefix) do
    if (Ord(B.Prefix[I]) < 33) or (Ord(B.Prefix[I]) > 126) or (B.Prefix[I] = ':') or (B.Prefix[I] = '-') then
      Bad := True;
  if Bad then
    Result := 'The ticket prefix must be exactly 3 printable ASCII characters, without ":" or "-" (for example TQR).';
end;

{ The identifier must be in the IANA list shipped with the installer (case matters, as in zoneinfo).
  Blank keeps the default, this machine's time zone. }
function ValidateTimeZone(const B: TBrand): String;
begin
  Result := '';
  if B.TimeZone = '' then
    Exit;
  if (Pos('|', B.TimeZone) > 0) or (Pos('|' + B.TimeZone + '|', KnownTimeZones) = 0) then
    Result := '"' + B.TimeZone + '" is not an IANA time zone identifier. Use a name such as Asia/Baku, Europe/Moscow or UTC (case matters).';
end;

function ValidateHost(const B: TBrand): String;
var
  I: Integer;
  C: Char;
  Bad: Boolean;
begin
  Result := '';
  Bad := False;
  for I := 1 to Length(B.Host) do
  begin
    C := B.Host[I];
    if not (((C >= 'a') and (C <= 'z')) or ((C >= 'A') and (C <= 'Z')) or ((C >= '0') and (C <= '9')) or (C = '.') or (C = '-') or (C = '_') or (C = ':')) then
      Bad := True;
  end;
  if Bad then
    Result := 'The host must be an IP address or a name such as 192.168.1.20 or tiqr.local. Leave it blank for 127.0.0.1.';
end;

function ValidatePort(const B: TBrand): String;
begin
  Result := '';
  if B.Port = '' then
    Exit;
  if not IsWholeNumber(B.Port) or (StrToInt(B.Port) < 1) or (StrToInt(B.Port) > 65535) then
    Result := 'The port must be a whole number from 1 to 65535.';
end;

function ValidatePem(const Path, What: String): String;
var
  Size: Integer;
  Content: AnsiString;
begin
  Result := '';
  if Path = '' then
    Result := 'Choose the ' + What + ' file.'
  else if not FileExists(Path) then
    Result := 'The ' + What + ' file was not found:' + NL + Path
  else if not FileSize(Path, Size) or (Size <= 0) or (Size > 1048576) or not LoadStringFromFile(Path, Content) then
    Result := 'The ' + What + ' file could not be read:' + NL + Path
  else if Pos('-----BEGIN', Content) = 0 then
    Result := 'The ' + What + ' file is not a PEM file:' + NL + Path;
end;

{ HTTPS is switched on by tls_cert and tls_key, and the app refuses one without the other. }
function ValidateTls(const B: TBrand): String;
begin
  Result := '';
  if not B.TlsOn then
    Exit;
  Result := ValidatePem(B.TlsCert, 'TLS certificate');
  if Result = '' then
    Result := ValidatePem(B.TlsKey, 'TLS private key');
end;

{ ---------------------------------------------------------------------------------------------
  The generator: the one place tiqr_brand.jsonc is written. Values reach it only through TBrand.
  The output is pure ASCII (other characters become \uXXXX escapes), so the file is valid JSONC in
  any encoding and carries no byte order mark, which the app's JSON parser rejects.
  --------------------------------------------------------------------------------------------- }

function HexDigits(Value: Integer): String;
begin
  { Pascal Script takes no const block inside a function, so the digits are written out here. }
  Result := Copy('0123456789abcdef', Value + 1, 1);
end;

function JsonString(const Text: String): String;
var
  I, Code: Integer;
  C: Char;
begin
  Result := '"';
  for I := 1 to Length(Text) do
  begin
    C := Text[I];
    Code := Ord(C);
    if C = '"' then
      Result := Result + '\"'
    else if C = '\' then
      Result := Result + '\\'
    else if Code = 8 then
      Result := Result + '\b'
    else if Code = 9 then
      Result := Result + '\t'
    else if Code = 10 then
      Result := Result + '\n'
    else if Code = 12 then
      Result := Result + '\f'
    else if Code = 13 then
      Result := Result + '\r'
    else if (Code < 32) or (Code > 126) then
      Result := Result + '\u' + HexDigits((Code div 4096) mod 16) + HexDigits((Code div 256) mod 16) + HexDigits((Code div 16) mod 16) + HexDigits(Code mod 16)
    else
      Result := Result + C;
  end;
  Result := Result + '"';
end;

function JsonText(const Text: String): String;
begin
  if Text = '' then
    Result := 'null'
  else
    Result := JsonString(Text);
end;

function JsonBool(Value: Boolean): String;
begin
  if Value then
    Result := 'true'
  else
    Result := 'false';
end;

function JsonWhole(const Text: String): String;
begin
  if Text = '' then
    Result := 'null'
  else
    Result := IntToStr(StrToInt(Text));
end;


{ A JSON array of strings from a list split on Separator; null when the list is empty. }
function JsonList(const Text: String; Separator: Char): String;
var
  Items: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if Text <> '' then
  begin
    Items := SplitText(Text, Separator);
    for I := 0 to GetArrayLength(Items) - 1 do
    begin
      if Result <> '' then
        Result := Result + ', ';
      Result := Result + JsonString(Items[I]);
    end;
  end;
  if Result = '' then
    Result := 'null'
  else
    Result := '[' + Result + ']';
end;

{ One `"key": value,` line with its note, indented by Indent. }
function Entry(const Indent, Key, Value, Note: String; Last: Boolean): String;
begin
  Result := Indent + '"' + Key + '": ' + Value;
  if not Last then
    Result := Result + ',';
  Result := Result + ' // ' + Note + NL;
end;

function BuildBrandJsonc(const B: TBrand): String;
begin
  Result :=
    '// Written by the TiQR installer. Read on every start from TIQR_HOME (beside the executable when unset).' + NL +
    '// Edit it by hand and restart TiQR to apply the change; no reinstall is needed.' + NL +
    '// Precedence: .env < .env.local < this file < environment. Null keeps the lower layer.' + NL +
    '// Never put TIQR_SECRET_KEY here; it belongs in .env.local.' + NL +
    '{' + NL +
    '  // Branding (required)' + NL +
    Entry('  ', 'app_name', JsonString(B.AppName), 'default: TiQR', False) +
    Entry('  ', 'logo_path', JsonText(B.LogoFile), 'default: none', False) +
    '  // "default" is vintage; or any Skeleton theme name (e.g. "cerberus", "dracula").' + NL +
    Entry('  ', 'theme', JsonText(B.Theme), 'default: default (vintage)', False) +
    '  // The browser''s language is used when offered; otherwise the first language is the default.' + NL +
    Entry('  ', 'languages', JsonList(B.Languages, '|'), 'default: en-US, ru-RU, az-AZ', False) +
    '  // The currencies a ticket type''s price may be in; chosen apart from the languages.' + NL +
    Entry('  ', 'currencies', JsonList(B.Currencies, '|'), 'default: USD, RUB, AZN (also KZT)', False) +
    NL +
    '  // Tickets' + NL +
    Entry('  ', 'prefix', JsonText(B.Prefix), 'default: TQR', False) +
    Entry('  ', 'default_tz', JsonText(B.TimeZone), 'default: this machine''s time zone, else UTC', False) +
    NL +
    '  // Web server (`tiqr serve`)' + NL +
    Entry('  ', 'host', JsonText(B.Host), 'default: 127.0.0.1', False) +
    Entry('  ', 'port', JsonWhole(B.Port), 'default: 7102', False) +
    Entry('  ', 'tls_cert', JsonText(B.TlsCert), 'default: none (plain HTTP)', False) +
    Entry('  ', 'tls_key', JsonText(B.TlsKey), 'default: none (plain HTTP)', False) +
    Entry('  ', 'server_printing', JsonBool(B.ServerPrinting), 'default: false', False) +
    NL +
    '  // BioStar is set up later from inside the web app; every field stays null.' + NL +
    '  "biostar": {' + NL +
    Entry('    ', 'base_url', 'null', 'default: none; set from the web app', False) +
    Entry('    ', 'username', 'null', 'default: none; set from the web app', False) +
    Entry('    ', 'password', 'null', 'default: none; set from the web app', False) +
    Entry('    ', 'device_ids', 'null', 'default: none; set from the web app', False) +
    Entry('    ', 'access_group_id', 'null', 'default: blank, TiQR manages its own group', False) +
    Entry('    ', 'verify_tls', 'null', 'default: false', False) +
    Entry('    ', 'timeout', 'null', 'default: 30 seconds', False) +
    Entry('    ', 'door_open_duration', 'null', 'default: 3 seconds', False) +
    Entry('    ', 'door_open_timeout', 'null', 'default: 10 seconds', True) +
    '  }' + NL +
    '}' + NL;
end;

{ ---------------------------------------------------------------------------------------------
  Reading the wizard into a TBrand
  --------------------------------------------------------------------------------------------- }

function ThemeValueAt(Index: Integer): String;
var
  Names: TArrayOfString;
begin
  Names := SplitText(ThemeNames, '|');
  Result := Names[Index];
  if Result = DefaultThemeName then
    Result := DefaultThemeValue;
end;

function ReadBrand: TBrand;
var
  Codes: TArrayOfString;
  I: Integer;
  Cert, Key: String;
begin
  Result.AppName := Trim(AppNameEdit.Text);
  Result.LogoSource := Trim(LogoEdit.Text);
  Result.LogoFile := '';
  if Result.LogoSource <> '' then
    Result.LogoFile := 'logo' + ExtractFileExt(Result.LogoSource);
  if ThemeCombo.ItemIndex >= 0 then
    Result.Theme := ThemeValueAt(ThemeCombo.ItemIndex)
  else
    Result.Theme := '';
  Result.Languages := '';
  Codes := SplitText(LanguageCodes, '|');
  for I := 0 to GetArrayLength(Codes) - 1 do
    if LanguageList.Checked[I] then
    begin
      if Result.Languages <> '' then
        Result.Languages := Result.Languages + '|';
      Result.Languages := Result.Languages + Codes[I];
    end;
  Result.Currencies := '';
  Codes := SplitText(CurrencyCodes, '|');
  for I := 0 to GetArrayLength(Codes) - 1 do
    if CurrencyList.Checked[I] then
    begin
      if Result.Currencies <> '' then
        Result.Currencies := Result.Currencies + '|';
      Result.Currencies := Result.Currencies + Codes[I];
    end;
  Result.Prefix := Trim(PrefixEdit.Text);
  Result.TimeZone := Trim(TimeZoneEdit.Text);
  Result.Host := Trim(NetworkPage.Values[0]);
  Result.Port := Trim(NetworkPage.Values[1]);
  Result.TlsOn := SecurityPage.Values[1];
  Result.TlsCert := '';
  Result.TlsKey := '';
  if Result.TlsOn then
  begin
    { Forward slashes read the same on Windows and need no escaping in JSON. }
    Cert := Trim(TlsFilesPage.Values[0]);
    Key := Trim(TlsFilesPage.Values[1]);
    StringChangeEx(Cert, '\', '/', True);
    StringChangeEx(Key, '\', '/', True);
    Result.TlsCert := Cert;
    Result.TlsKey := Key;
  end;
  Result.ServerPrinting := SecurityPage.Values[0];
end;

{ The error for one page, or '' when it is fine (or is not a page with input). }
function ValidatePage(PageID: Integer; const B: TBrand): String;
begin
  Result := '';
  if PageID = AppPage.ID then
  begin
    Result := ValidateAppName(B);
    if Result = '' then Result := ValidateLogo(B);
    if Result = '' then Result := ValidateTheme(B);
    if Result = '' then Result := ValidatePrefix(B);
  end
  else if PageID = RegionPage.ID then
  begin
    Result := ValidateTimeZone(B);
    if Result = '' then Result := ValidateLanguages(B);
    if Result = '' then Result := ValidateCurrencies(B);
  end
  else if PageID = NetworkPage.ID then
  begin
    Result := ValidateHost(B);
    if Result = '' then Result := ValidatePort(B);
  end
  else if PageID = TlsFilesPage.ID then
    Result := ValidateTls(B);
end;

{ Both or neither. A URL must be http or https; neither value may hold a double quote or a percent sign,
  since they are passed to tiqr install on the cmd command line. }
function ValidatePassWebhook(const Url, Secret: String): String;
begin
  Result := '';
  if (Url = '') and (Secret = '') then
    Exit;
  if Url = '' then
    Result := 'Enter the webhook URL too, or clear the secret.'
  else if Secret = '' then
    Result := 'Enter the webhook secret too, or clear the URL.'
  else if (Pos('"', Url + Secret) > 0) or (Pos('%', Url + Secret) > 0) then
    Result := 'The webhook URL and secret must not contain double quotes or percent signs.'
  else if (Pos('http://', Lowercase(Url)) <> 1) and (Pos('https://', Lowercase(Url)) <> 1) then
    Result := 'The webhook URL must start with http:// or https://.';
end;

function ValidateAll(const B: TBrand): String;
begin
  Result := ValidateAppName(B);
  if Result = '' then Result := ValidateLogo(B);
  if Result = '' then Result := ValidateTheme(B);
  if Result = '' then Result := ValidateLanguages(B);
  if Result = '' then Result := ValidateCurrencies(B);
  if Result = '' then Result := ValidatePrefix(B);
  if Result = '' then Result := ValidateTimeZone(B);
  if Result = '' then Result := ValidateHost(B);
  if Result = '' then Result := ValidatePort(B);
  if Result = '' then Result := ValidateTls(B);
end;

{ ---------------------------------------------------------------------------------------------
  Custom pages
  --------------------------------------------------------------------------------------------- }

procedure ThemeLinkClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if not ShellExec('open', SkeletonThemesUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox('Open this address in a browser to preview the themes:' + NL + SkeletonThemesUrl, mbInformation, MB_OK);
end;

function AddCaption(Page: TWizardPage; Left, Top, Width: Integer; const Text: String): TNewStaticText;
begin
  Result := TNewStaticText.Create(Page);
  Result.Parent := Page.Surface;
  Result.Left := Left;
  Result.Top := Top;
  Result.Width := Width;
  Result.AutoSize := False;
  Result.Height := ScaleY(16);
  Result.Caption := Text;
end;

function AddEdit(Page: TWizardPage; Left, Top, Width: Integer): TNewEdit;
begin
  Result := TNewEdit.Create(Page);
  Result.Parent := Page.Surface;
  Result.Left := Left;
  Result.Top := Top;
  Result.Width := Width;
end;

procedure LogoBrowseClick(Sender: TObject);
var
  FileName: String;
begin
  FileName := Trim(LogoEdit.Text);
  if GetOpenFileName('Choose a logo', FileName, '', 'Images (*.png;*.svg;*.jpg;*.jpeg)|*.png;*.svg;*.jpg;*.jpeg|All files (*.*)|*.*', '.png') then
    LogoEdit.Text := FileName;
end;

procedure CreateAppPage;
var
  Names: TArrayOfString;
  Link: TNewStaticText;
  Browse: TNewButton;
  I, Y: Integer;
begin
  AppPage := CreateCustomPage(wpSelectDir, 'App', 'Name the app, set the ticket prefix, then choose its logo and theme.');
  Y := 0;

  AddCaption(AppPage, 0, Y, AppPage.SurfaceWidth, 'App name (required):');
  AppNameEdit := AddEdit(AppPage, 0, Y + ScaleY(18), AppPage.SurfaceWidth);
  AppNameEdit.Text := 'TiQR';
  Y := Y + ScaleY(46);

  AddCaption(AppPage, 0, Y, AppPage.SurfaceWidth, 'Ticket prefix: exactly 3 printable ASCII characters. Blank keeps TQR.');
  PrefixEdit := AddEdit(AppPage, 0, Y + ScaleY(18), AppPage.SurfaceWidth);
  PrefixEdit.Text := DefaultPrefix;
  Y := Y + ScaleY(46);

  AddCaption(AppPage, 0, Y, AppPage.SurfaceWidth, 'Logo (optional): PNG, SVG or JPG. Blank keeps the built-in logo.');
  LogoEdit := AddEdit(AppPage, 0, Y + ScaleY(18), AppPage.SurfaceWidth - ScaleX(88));
  Browse := TNewButton.Create(AppPage);
  Browse.Parent := AppPage.Surface;
  Browse.Caption := 'Browse...';
  Browse.Left := AppPage.SurfaceWidth - ScaleX(80);
  Browse.Top := Y + ScaleY(17);
  Browse.Width := ScaleX(80);
  Browse.Height := ScaleY(23);
  Browse.OnClick := @LogoBrowseClick;
  Y := Y + ScaleY(46);

  AddCaption(AppPage, 0, Y, AppPage.SurfaceWidth, '"vintage" is the default theme. Preview the 24 Skeleton themes at:');
  Y := Y + ScaleY(18);
  Link := TNewStaticText.Create(AppPage);
  Link.Parent := AppPage.Surface;
  Link.Left := 0;
  Link.Top := Y;
  Link.Caption := SkeletonThemesUrl;
  Link.Cursor := crHand;
  Link.Font.Style := Link.Font.Style + [fsUnderline];
  Link.Font.Color := clBlue;
  Link.OnClick := @ThemeLinkClick;
  Y := Y + ScaleY(20);

  ThemeCombo := TNewComboBox.Create(AppPage);
  ThemeCombo.Parent := AppPage.Surface;
  ThemeCombo.Left := 0;
  ThemeCombo.Top := Y;
  ThemeCombo.Width := AppPage.SurfaceWidth;
  ThemeCombo.Style := csDropDownList;
  Names := SplitText(ThemeNames, '|');
  for I := 0 to GetArrayLength(Names) - 1 do
  begin
    if Names[I] = DefaultThemeName then
    begin
      ThemeCombo.Items.Add(Names[I] + ' (default)');
      ThemeCombo.ItemIndex := I;
    end
    else
      ThemeCombo.Items.Add(Names[I]);
  end;
end;

procedure CreateRegionPage;
var
  Labels, Codes: TArrayOfString;
  Half, I, Y: Integer;
begin
  RegionPage := CreateCustomPage(AppPage.ID, 'Region', 'Choose the time zone, the languages and the currencies.');
  Y := 0;
  Half := (RegionPage.SurfaceWidth - ScaleX(16)) div 2;

  AddCaption(RegionPage, 0, Y, RegionPage.SurfaceWidth, 'Time zone (IANA name, such as Asia/Baku). Blank uses this machine''s time zone.');
  TimeZoneEdit := AddEdit(RegionPage, 0, Y + ScaleY(18), RegionPage.SurfaceWidth);
  Y := Y + ScaleY(46);

  AddCaption(RegionPage, 0, Y, Half, 'Languages (tick at least one):');
  AddCaption(RegionPage, Half + ScaleX(16), Y, Half, 'Currencies (tick at least one):');
  Y := Y + ScaleY(18);

  LanguageList := TNewCheckListBox.Create(RegionPage);
  LanguageList.Parent := RegionPage.Surface;
  LanguageList.Left := 0;
  LanguageList.Top := Y;
  LanguageList.Width := Half;
  LanguageList.Height := ScaleY(96);
  Labels := SplitText(LanguageLabels, '|');
  Codes := SplitText(LanguageCodes, '|');
  for I := 0 to GetArrayLength(Labels) - 1 do
  begin
    LanguageList.Items.Add(Labels[I]);
    LanguageList.Checked[I] := Pos('|' + Codes[I] + '|', '|' + DefaultLanguages + '|') > 0;
  end;

  CurrencyList := TNewCheckListBox.Create(RegionPage);
  CurrencyList.Parent := RegionPage.Surface;
  CurrencyList.Left := Half + ScaleX(16);
  CurrencyList.Top := Y;
  CurrencyList.Width := Half;
  CurrencyList.Height := ScaleY(96);
  Labels := SplitText(CurrencyLabels, '|');
  Codes := SplitText(CurrencyCodes, '|');
  for I := 0 to GetArrayLength(Labels) - 1 do
  begin
    CurrencyList.Items.Add(Labels[I]);
    CurrencyList.Checked[I] := Pos('|' + Codes[I] + '|', '|' + DefaultCurrencies + '|') > 0;
  end;
end;

procedure CreateWizardPages;
begin
  { 1. App: name, logo, prefix and theme }
  CreateAppPage;

  { 2. Region: time zone, languages and currencies }
  CreateRegionPage;

  { 3. Network: host and port }
  NetworkPage := CreateInputQueryPage(RegionPage.ID, 'Network', 'Where should the server listen?', 'Use the server''s LAN address, not 0.0.0.0. Blank keeps 127.0.0.1. The port is a whole number from 1 to 65535; blank keeps 7102.');
  NetworkPage.Add('Host:', False);
  NetworkPage.Values[0] := DefaultHost;
  NetworkPage.Add('Port:', False);
  NetworkPage.Values[1] := DefaultPort;

  { 4. Pass webhook: optional, and both or neither. The secret is masked on the page. }
  PassWebhookPage := CreateInputQueryPage(NetworkPage.ID, 'Pass webhook', 'Where should each new pass be posted? (optional)', 'Leave both blank for none. TiQR POSTs each new passage to the URL, signed with the secret.');
  PassWebhookPage.Add('Webhook URL (https://...):', False);
  PassWebhookPage.Add('Webhook secret:', True);

  { 5. Security and printing: HTTPS on or off, and server printing on or off }
  SecurityPage := CreateInputOptionPage(PassWebhookPage.ID, 'Security and printing', 'Should the server use HTTPS, and print on its own printer?', 'HTTPS needs a certificate and its private key; the next page asks for them. Server printing lets operators print badges on the server''s default printer from the web UI.', False, False);
  SecurityPage.Add('Server printing');
  SecurityPage.Add('Use HTTPS (plain HTTP when off)');

  { 6. TLS certificate files, shown only when HTTPS is ticked (tls_cert and tls_key are the schema's TLS keys). }
  TlsFilesPage := CreateInputFilePage(SecurityPage.ID, 'TLS certificate', 'Choose the certificate and key for HTTPS.', 'Both PEM files are used from where they are; keep them in place. Set them up so the TiQR service account can read the key.');
  TlsFilesPage.Add('Certificate (PEM):', 'PEM files (*.pem;*.crt;*.cer)|*.pem;*.crt;*.cer|All files (*.*)|*.*', '.pem');
  TlsFilesPage.Add('Private key (PEM):', 'PEM files (*.pem;*.key)|*.pem;*.key|All files (*.*)|*.*', '.key');
end;

{ ---------------------------------------------------------------------------------------------
  Wizard events
  --------------------------------------------------------------------------------------------- }

procedure LoadKnownTimeZones;
var
  Raw: AnsiString;
  Text: String;
begin
  ExtractTemporaryFile('timezones.txt');
  KnownTimeZones := '|';
  if LoadStringFromFile(ExpandConstant('{tmp}\timezones.txt'), Raw) then
  begin
    Text := String(Raw);
    StringChangeEx(Text, #13, '', True);
    StringChangeEx(Text, #10, '|', True);
    KnownTimeZones := '|' + Text;
    if Copy(KnownTimeZones, Length(KnownTimeZones), 1) <> '|' then
      KnownTimeZones := KnownTimeZones + '|';
  end;
end;

procedure InitializeWizard;
begin
  LoadKnownTimeZones;
  CreateWizardPages;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = TlsFilesPage.ID then
    Result := not SecurityPage.Values[1];
end;

{ Nothing moves forward until the page's values pass; the message says what to fix. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  Result := True;
  if CurPageID = PassWebhookPage.ID then
    Problem := ValidatePassWebhook(Trim(PassWebhookPage.Values[0]), Trim(PassWebhookPage.Values[1]))
  else
    Problem := ValidatePage(CurPageID, ReadBrand);
  if Problem <> '' then
  begin
    MsgBox(Problem, mbError, MB_OK);
    Result := False;
  end;
end;

{ ---------------------------------------------------------------------------------------------
  Install: stage the files, then let Setup copy them
  --------------------------------------------------------------------------------------------- }

function LogoChosen: Boolean;
begin
  Result := ReadBrand.LogoFile <> '';
end;

function LogoFileName(Param: String): String;
begin
  Result := ReadBrand.LogoFile;
end;

function LogoStagedPath(Param: String): String;
begin
  Result := ExpandConstant('{tmp}\') + ReadBrand.LogoFile;
end;

{ An existing install (its folder, its data folder or its service) is asked about before the wizard starts.
  The first question is reinstall or update. An update keeps the database, settings and license and replaces
  only the program; a reinstall removes everything at ssInstall and installs from scratch. Cancel changes nothing. }
function InitializeSetup(): Boolean;
var
  ResultCode, Answer: Integer;
begin
  Result := True;
  Updating := False;
  Reinstalling := DirExists(ExpandConstant('{autopf}\TiQR')) or DirExists(ExpandConstant('{commonappdata}\TiQR'));
  if not Reinstalling then
    Reinstalling := Exec(ExpandConstant('{sys}\sc.exe'), 'query TiQR', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if Reinstalling then
  begin
    Answer := MsgBox('TiQR is already installed. Is this a reinstall or an update?' + NL + NL + 'Yes: update. Keeps the database, users, settings and license; only the program is replaced.' + NL + 'No: reinstall. Deletes the program and all its data, including the database and users.' + NL + 'Cancel: stop the setup; nothing is changed.', mbConfirmation, MB_YESNOCANCEL);
    if Answer = IDYES then
    begin
      Updating := True;
      Reinstalling := False;
    end
    else if Answer = IDNO then
    begin
      if MsgBox('This deletes all data, including the database and users, and starts from scratch. Continue?', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end
    else
      Result := False;
  end;
end;

{ The folder the app reads tiqr_brand.jsonc and its logo from when TIQR_HOME is unset. }
function DataFolder: String;
begin
  Result := ExpandConstant('{commonappdata}\TiQR');
end;

{ A reinstall starts from scratch: the service is stopped first, since it runs the program being replaced,
  then the program folder (only when it holds TiQR) and the data folder are removed, database included. }
procedure RemoveExistingInstall;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\net.exe'), 'stop TiQR', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if FileExists(ExpandConstant('{app}\tiqr.exe')) then
    DelTree(ExpandConstant('{app}'), True, True, True);
  DelTree(DataFolder, True, True, True);
end;

{ Runs when the user confirms the install and before anything is written. A message returned here
  stops the install and is shown to the user. The logo is copied out of the user's folder first, so
  deleting the original from then on changes nothing. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Brand: TBrand;
  Json: String;
  ResultCode: Integer;
begin
  Result := '';
  Brand := ReadBrand;
  Result := ValidateAll(Brand);
  if Result = '' then
    Result := ValidatePassWebhook(Trim(PassWebhookPage.Values[0]), Trim(PassWebhookPage.Values[1]));
  if Result <> '' then
    Exit;

  if Brand.LogoFile <> '' then
  begin
    DeleteFile(LogoStagedPath(''));
    if not FileCopy(Brand.LogoSource, LogoStagedPath(''), False) or not FileExists(LogoStagedPath('')) then
    begin
      Result := 'The logo could not be copied, so nothing was installed:' + NL + Brand.LogoSource + NL + NL + 'Check that the file can be read, or clear the logo and try again.';
      Exit;
    end;
  end;

  Json := BuildBrandJsonc(Brand);
  DeleteFile(ExpandConstant('{tmp}\' + BrandFile));
  if not SaveStringToFile(ExpandConstant('{tmp}\' + BrandFile), AnsiString(Json), False) then
    Result := 'The settings file could not be prepared, so nothing was installed.'
  else if Reinstalling then
    RemoveExistingInstall
  else if Updating then
    { The service runs the program being replaced, so it is stopped before the files are copied. }
    Exec(ExpandConstant('{sys}\net.exe'), 'stop TiQR', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Existing: String;
  Brand: TBrand;
  Host, Port, Confirmed: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    { A first install or reinstall has no settings file here, so the wizard's file is placed here. An update
      that finds one leaves it to tiqr install, which saves it as tiqr_brand.jsonc.bak and replaces it. }
    ForceDirectories(DataFolder);
    Existing := DataFolder + '\' + BrandFile;
    if Updating and FileExists(Existing) then
      Log('Update: tiqr install will replace ' + Existing + ' and keep the previous file as .bak')
    else if not FileCopy(ExpandConstant('{app}\' + BrandFile), Existing, False) then
      MsgBox('TiQR was copied, but ' + Existing + ' could not be written. Copy tiqr_brand.jsonc there by hand, then run tiqr.exe install.', mbError, MB_OK);
    { tiqr install registers the service, opens the firewall and runs the health check. The address and
      port come from the wizard so .env.local does not hold different values from the settings file. }
    Brand := ReadBrand;
    Host := Brand.Host;
    if Host = '' then
      Host := DefaultHost;
    Port := Brand.Port;
    if Port = '' then
      Port := DefaultPort;
    { The window is visible, so install can ask for the first admin, as the terminal install does. It
      closes on success; a failure waits for Enter so the error stays readable, and no popup is shown.
      tiqr install opens the browser itself once the health check has passed. }
    { The reinstall was confirmed in InitializeSetup, so tiqr install does not ask again. }
    Confirmed := '';
    if Reinstalling then
      Confirmed := 'set TIQR_REINSTALL_CONFIRMED=1&& ';
    if Updating then
      Confirmed := 'set TIQR_UPDATE_CONFIRMED=1&& ';
    { cmd strips the outer quote, so exactly one more quote may open the executable's path. }
    Log('Running tiqr install in a console window');
    { The webhook goes as flags, so the console does not ask for it again; blank values mean none. }
    if not Exec(ExpandConstant('{cmd}'), '/C "' + Confirmed + '"' + ExpandConstant('{app}\tiqr.exe') + '" install --source "' + ExpandConstant('{app}') + '" --host ' + Host + ' --port ' + Port + ' --pass-webhook-url "' + Trim(PassWebhookPage.Values[0]) + '" --pass-webhook-secret "' + Trim(PassWebhookPage.Values[1]) + '" || (pause & exit /b 1)"', ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
    begin
      Log('The console window could not be started');
      MsgBox('TiQR was copied, but the setup window could not be started. Open Command Prompt as administrator and run:' + NL + '"' + ExpandConstant('{app}\tiqr.exe') + '" install', mbError, MB_OK);
    end
    else
      Log('tiqr install finished with exit code ' + IntToStr(ResultCode));
  end;
end;

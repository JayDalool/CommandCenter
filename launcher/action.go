package main

// Native terminal actions: CommandCenter.exe "commandcenter://terminal/..."
//
// Any web page can ask the browser to open a commandcenter: link, so the URI
// is treated as hostile. It only ever selects one of three fixed actions and
// a project key that must match ^[A-Z][A-Z0-9]{1,5}$. The command, the host
// and every argument come from this file and the validated launcher.json,
// never from the URI. Nothing is typed into the terminal.

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
)

const (
	ActionClaude = "claude"
	ActionRepo   = "repo"
	ActionServer = "server"

	uriScheme  = "commandcenter"
	maxURI     = 200
	ccTerminal = "/srv/server/repos/CommandCenter/scripts/cc-terminal"
	wtWindow   = "CommandCenter"
)

// Action is one parsed, validated commandcenter: link.
type Action struct {
	Kind    string // ActionClaude, ActionRepo or ActionServer
	Project string // "" for server; else matches projectRE
}

var projectRE = regexp.MustCompile(`^[A-Z][A-Z0-9]{1,5}$`)

// IsActionURI says whether a command-line argument asks for action mode.
func IsActionURI(arg string) bool {
	return len(arg) >= len(uriScheme)+1 && strings.EqualFold(arg[:len(uriScheme)+1], uriScheme+":")
}

func hasActionURI(args []string) bool {
	for _, a := range args {
		if IsActionURI(a) {
			return true
		}
	}
	return false
}

// uriByteOK is the whole alphabet a valid link can use. Everything else
// (%, &, ;, |, `, $, quotes, spaces, @, #, ., control and non-ASCII
// characters) is refused before any parsing happens.
func uriByteOK(c byte) bool {
	return c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' ||
		c == ':' || c == '/' || c == '?' || c == '='
}

// parseAction accepts only
//
//	commandcenter://terminal/claude?project=KEY
//	commandcenter://terminal/repo?project=KEY
//	commandcenter://terminal/server
//
// with an optional single "/" after the action. Scheme, host and action are
// case-insensitive; the parameter name is exact; a key written in lowercase
// letters/digits is upper-cased before it is checked.
func parseAction(uri string) (Action, error) {
	if len(uri) > maxURI {
		return Action{}, fmt.Errorf("the link is longer than %d characters", maxURI)
	}
	for i := 0; i < len(uri); i++ {
		if !uriByteOK(uri[i]) {
			return Action{}, fmt.Errorf("the link contains a character that is not allowed (%q)", uri[i])
		}
	}
	prefix := uriScheme + "://"
	if len(uri) < len(prefix) || !strings.EqualFold(uri[:len(prefix)], prefix) {
		return Action{}, errors.New("the link does not start with commandcenter://")
	}
	rest := uri[len(prefix):]
	if strings.Contains(rest, ":") {
		return Action{}, errors.New("the link may not name a port")
	}
	path, query, hasQuery := strings.Cut(rest, "?")
	if strings.Contains(query, "?") {
		return Action{}, errors.New("the link has more than one '?'")
	}
	path = strings.TrimSuffix(path, "/")
	parts := strings.Split(path, "/")
	if len(parts) != 2 || !strings.EqualFold(parts[0], "terminal") {
		return Action{}, errors.New("only commandcenter://terminal/... links are supported")
	}
	var a Action
	switch strings.ToLower(parts[1]) {
	case ActionClaude:
		a.Kind = ActionClaude
	case ActionRepo:
		a.Kind = ActionRepo
	case ActionServer:
		a.Kind = ActionServer
	default:
		return Action{}, errors.New("unknown terminal kind (expected claude, repo or server)")
	}
	if a.Kind == ActionServer {
		if hasQuery {
			return Action{}, errors.New("a server terminal takes no parameters")
		}
		return a, nil
	}
	if !hasQuery {
		return Action{}, errors.New("the link names no project")
	}
	key, ok := strings.CutPrefix(query, "project=")
	if !ok || strings.Contains(key, "=") {
		return Action{}, errors.New("the only allowed parameter is project=KEY")
	}
	key = strings.ToUpper(key) // only letters and digits can reach here
	if !projectRE.MatchString(key) {
		return Action{}, errors.New("the project key must be 2-6 letters/digits starting with a letter")
	}
	a.Project = key
	return a, nil
}

// projectNames are display names for tab titles only; they never reach a command.
var projectNames = map[string]string{
	"SV":   "SamVision",
	"GZ":   "GauzeMate",
	"MFE":  "MyFamilyExpenses",
	"CC":   "Command Center",
	"GYST": "GYST / LifeOps",
}

func displayName(key string) string {
	if n, ok := projectNames[key]; ok {
		return n
	}
	return key
}

func terminalTitle(a Action, cfg Config) string {
	switch a.Kind {
	case ActionClaude:
		return "Claude — " + displayName(a.Project)
	case ActionRepo:
		return "Repo — " + displayName(a.Project)
	default:
		return "Server — " + cfg.Host
	}
}

// terminalSSHArgs: interactive (-t, no BatchMode, no -N). The host sits after
// "--"; the remote command is fixed and its only variable part is the key.
func terminalSSHArgs(a Action, cfg Config) []string {
	args := []string{
		"-t",
		"-o", "ServerAliveInterval=30",
		"-o", "ServerAliveCountMax=3",
		"--", cfg.Host,
	}
	if a.Kind == ActionClaude || a.Kind == ActionRepo {
		args = append(args, ccTerminal, a.Kind, a.Project)
	}
	return args
}

// terminalArgv is the process to start: Windows Terminal (one window named
// CommandCenter, a new tab per action) when wt != "", else PowerShell in a new
// console window.
func terminalArgv(a Action, cfg Config, wt, ssh, ps string) (string, []string) {
	title := terminalTitle(a, cfg)
	sargs := terminalSSHArgs(a, cfg)
	if wt != "" {
		// --suppressApplicationTitle keeps "Claude — SamVision" even when the remote program sets its own title.
		args := []string{"-w", wtWindow, "new-tab", "--title", title, "--suppressApplicationTitle", "--", ssh}
		return wt, append(args, sargs...)
	}
	return ps, []string{"-NoLogo", "-NoExit", "-Command", psCommand(title, ssh, sargs)}
}

// psQuote makes a PowerShell single-quoted string. PowerShell also treats the
// typographic single quotes as quote characters, so those are doubled too.
func psQuote(s string) string {
	var b strings.Builder
	b.WriteByte('\'')
	for _, r := range s {
		switch r {
		case '\'', '\u2018', '\u2019', '\u201A', '\u201B':
			b.WriteRune(r)
		}
		b.WriteRune(r)
	}
	b.WriteByte('\'')
	return b.String()
}

func psCommand(title, ssh string, args []string) string {
	var b strings.Builder
	b.WriteString("$Host.UI.RawUI.WindowTitle=" + psQuote(title) + "; & " + psQuote(ssh))
	for _, a := range args {
		b.WriteString(" " + psQuote(a))
	}
	return b.String()
}

// FindWT: the Windows Terminal app alias, else wt.exe on PATH. "" = not installed.
func FindWT(getenv func(string) string, exists func(string) bool, lookPath func(string) (string, error)) string {
	if base := getenv("LOCALAPPDATA"); base != "" {
		if p := winJoin(base, "Microsoft", "WindowsApps", "wt.exe"); exists(p) {
			return p
		}
	}
	if p, err := lookPath("wt.exe"); err == nil && p != "" {
		return p
	}
	return ""
}

func powerShellPath(getenv func(string) string) string {
	root := getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return winJoin(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
}

// escapeArg is syscall.EscapeArg (Windows) re-implemented so its result can
// be checked on Linux. platform_windows_test.go compares it with the real one.
func escapeArg(s string) string {
	if s == "" {
		return `""`
	}
	needsBackslash, hasSpace := false, false
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case '"', '\\':
			needsBackslash = true
		case ' ', '\t':
			hasSpace = true
		}
	}
	if !needsBackslash && !hasSpace {
		return s
	}
	if !needsBackslash {
		return `"` + s + `"`
	}
	var b strings.Builder
	if hasSpace {
		b.WriteByte('"')
	}
	slashes := 0
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch c {
		case '\\':
			slashes++
		case '"':
			for ; slashes > 0; slashes-- {
				b.WriteByte('\\')
			}
			b.WriteByte('\\')
		default:
			slashes = 0
		}
		b.WriteByte(c)
	}
	if hasSpace {
		for ; slashes > 0; slashes-- {
			b.WriteByte('\\')
		}
		b.WriteByte('"')
	}
	return b.String()
}

// commandLine is the string CreateProcess receives from os/exec: the program
// path is only wrapped in quotes when it has a space or tab (it cannot hold a
// '"'), every other argument goes through escapeArg.
func commandLine(exe string, args []string) string {
	parts := make([]string, 0, len(args)+1)
	if strings.ContainsAny(exe, " \t") {
		parts = append(parts, `"`+exe+`"`)
	} else {
		parts = append(parts, exe)
	}
	for _, a := range args {
		parts = append(parts, escapeArg(a))
	}
	return strings.Join(parts, " ")
}

// openTerminal starts the visible terminal for a. It never waits on it.
func openTerminal(p Platform, log *logger, cfg Config, a Action) error {
	sshPath, ok := FindSSH(p.Getenv, p.Exists, p.LookPath)
	if !ok {
		return errors.New("the Windows OpenSSH client (ssh.exe) was not found.\n\nInstall it from Settings > System > Optional features > OpenSSH Client")
	}
	ps := powerShellPath(p.Getenv)
	exe, args := terminalArgv(a, cfg, FindWT(p.Getenv, p.Exists, p.LookPath), sshPath, ps)
	log.Printf("terminal %s %s via %s", a.Kind, a.Project, exe)
	err := p.StartTerminal(exe, args, exe == ps)
	if err != nil && exe != ps {
		// Windows Terminal is there but would not start: fall back to a PowerShell console.
		log.Printf("windows terminal failed (%v); falling back to powershell", err)
		exe, args = terminalArgv(a, cfg, "", sshPath, ps)
		err = p.StartTerminal(exe, args, true)
	}
	return err
}

const actionFail = "Command Center can't open that terminal: "

// runAction is the whole program for CommandCenter.exe "commandcenter:...":
// no mutex, no tunnel, no browser. It starts one terminal window and exits.
func runAction(p Platform, log *logger, uri string) int {
	a, err := parseAction(uri)
	if err != nil {
		log.Printf("action refused: %v", err)
		p.Alert(actionFail+err.Error()+".", true)
		return 2
	}
	cfg, cfgPath, err := loadConfig(p)
	if err != nil {
		p.Alert(fmt.Sprintf(actionFail+"the settings file has a problem:\n%s\n\n%v", cfgPath, err), true)
		return 2
	}
	if err := openTerminal(p, log, cfg, a); err != nil {
		log.Printf("terminal failed: %v", err)
		p.Alert(actionFail+err.Error(), true)
		return 1
	}
	return 0
}

// regValue is one value under HKEY_CURRENT_USER.
type regValue struct {
	Key  string // relative to HKCU
	Name string // "" = the key's (Default) value
	Data string // REG_SZ
}

// protocolRegistry is the per-user commandcenter: URL protocol registration
// pointing at exe. exe must be an absolute Windows path.
func protocolRegistry(exe string) ([]regValue, error) {
	abs := len(exe) > 3 && (exe[1] == ':' && exe[2] == '\\' || strings.HasPrefix(exe, `\\`))
	if !abs || strings.ContainsAny(exe, "\"\x00\r\n") {
		return nil, fmt.Errorf("not an absolute Windows path: %q", exe)
	}
	const k = `Software\Classes\` + uriScheme
	q := `"` + exe + `"`
	return []regValue{
		{k, "", "URL:Command Center"},
		{k, "URL Protocol", ""},
		{k + `\DefaultIcon`, "", q + ",0"},
		{k + `\shell\open\command`, "", q + ` "%1"`},
	}, nil
}

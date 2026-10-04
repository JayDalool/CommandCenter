package main

import (
	"reflect"
	"strings"
	"testing"
)

const (
	tWT  = `C:\Users\jay\AppData\Local\Microsoft\WindowsApps\wt.exe`
	tSSH = `C:\Windows\System32\OpenSSH\ssh.exe`
	tPS  = `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
)

func TestParseActionAccepts(t *testing.T) {
	cases := map[string]Action{
		"commandcenter://terminal/claude?project=SV":   {ActionClaude, "SV"},
		"commandcenter://terminal/claude/?project=GZ":  {ActionClaude, "GZ"},
		"commandcenter://terminal/repo?project=MFE":    {ActionRepo, "MFE"},
		"commandcenter://terminal/repo?project=GYST":   {ActionRepo, "GYST"},
		"commandcenter://terminal/repo?project=CC":     {ActionRepo, "CC"},
		"commandcenter://terminal/repo?project=sv":     {ActionRepo, "SV"},
		"commandcenter://terminal/repo?project=A1B2C3": {ActionRepo, "A1B2C3"},
		"commandcenter://terminal/server":              {ActionServer, ""},
		"commandcenter://terminal/server/":             {ActionServer, ""},
		"CommandCenter://TERMINAL/Claude?project=SV":   {ActionClaude, "SV"},
		"COMMANDCENTER://Terminal/SERVER":              {ActionServer, ""},
	}
	for uri, want := range cases {
		got, err := parseAction(uri)
		if err != nil || got != want {
			t.Errorf("%q: got %+v, %v; want %+v", uri, got, err, want)
		}
	}
}

func TestParseActionRejects(t *testing.T) {
	bad := []string{
		"",
		"commandcenter:",
		"commandcenter:terminal/server",
		"commandcenter:/terminal/server",
		"commandcenter://terminal",
		"commandcenter://terminal/",
		"commandcenter://terminal//server",
		"commandcenter://terminal/server//",
		"commandcenter://terminal/shell",
		"commandcenter://terminal/claude",
		"commandcenter://terminal/claude?",
		"commandcenter://terminal/repo?project=",
		"commandcenter://terminal/claude?project=SV;calc",
		"commandcenter://terminal/claude?project=SV%26calc",
		"commandcenter://terminal/claude?project=%53V",
		"commandcenter://terminal/claude?project=SV&project=GZ",
		"commandcenter://terminal/claude?project=SV&cmd=x",
		"commandcenter://terminal/claude?project=SV?project=GZ",
		"commandcenter://terminal/claude?project=SV=x",
		"commandcenter://terminal/claude?Project=SV",
		"commandcenter://terminal/claude?host=evil",
		"commandcenter://terminal/claude?project=SV&host=evil",
		"commandcenter://terminal/server?host=evil",
		"commandcenter://terminal/server?project=SV",
		"commandcenter://evil/claude?project=SV",
		"commandcenter://terminal.evil/claude?project=SV",
		"commandcenter://terminal/claude?project=../x",
		"commandcenter://terminal/claude/../server",
		"commandcenter://user@terminal/claude?project=SV",
		"commandcenter://terminal:22/claude?project=SV",
		"commandcenter://terminal/claude?project=SV#x",
		"commandcenter://terminal/claude?project=SV x",
		"commandcenter://terminal/claude?project=SV\"",
		"commandcenter://terminal/claude?project=SV'",
		"commandcenter://terminal/claude?project=SV|calc",
		"commandcenter://terminal/claude?project=SV`calc`",
		"commandcenter://terminal/claude?project=$SV",
		"commandcenter://terminal/claude?project=SV\n",
		"commandcenter://terminal/claude?project=SV\x00",
		"commandcenter://terminal/claude?project=SV\t",
		"commandcenter://terminal/claude?project=SV\\",
		"commandcenter://terminal/claude?project=1SV",
		"commandcenter://terminal/claude?project=S",
		"commandcenter://terminal/claude?project=SEVENCH",
		"commandcenter://terminal/claude?project=S_V",
		"commandcenter://terminal/claude?project=SV-1",
		"commandcenter://terminal/claude?project=ＳＶ",
		"commandcenter://terminal/claude?project=SV/",
		"commandcenter://terminal/claude/x?project=SV",
		"http://terminal/claude?project=SV",
		"commandcenterx://terminal/server",
		"commandcenter://terminal/server" + strings.Repeat("/", 200),
	}
	for _, uri := range bad {
		if a, err := parseAction(uri); err == nil {
			t.Errorf("%q accepted as %+v", uri, a)
		}
	}
	long := "commandcenter://terminal/claude?project=SV" + strings.Repeat("A", 200)
	if _, err := parseAction(long); err == nil || !strings.Contains(err.Error(), "longer than 200") {
		t.Errorf("long: %v", err)
	}
}

func TestIsActionURI(t *testing.T) {
	for s, want := range map[string]bool{
		"commandcenter://terminal/server": true, "COMMANDCENTER:x": true, "commandcenter:": true,
		"commandcenter": false, "--commandcenter:": false, "": false, "http://x": false,
	} {
		if IsActionURI(s) != want {
			t.Errorf("%q: want %v", s, want)
		}
	}
}

func TestTerminalArgvWT(t *testing.T) {
	cfg := DefaultConfig()
	cases := []struct {
		a     Action
		title string
		tail  []string
	}{
		{Action{ActionClaude, "SV"}, "Claude — SamVision", []string{ccTerminal, "claude", "SV"}},
		{Action{ActionClaude, "GZ"}, "Claude — GauzeMate", []string{ccTerminal, "claude", "GZ"}},
		{Action{ActionRepo, "SV"}, "Repo — SamVision", []string{ccTerminal, "repo", "SV"}},
		{Action{ActionRepo, "GZ"}, "Repo — GauzeMate", []string{ccTerminal, "repo", "GZ"}},
		{Action{ActionRepo, "MFE"}, "Repo — MyFamilyExpenses", []string{ccTerminal, "repo", "MFE"}},
		{Action{ActionRepo, "CC"}, "Repo — Command Center", []string{ccTerminal, "repo", "CC"}},
		{Action{ActionRepo, "GYST"}, "Repo — GYST / LifeOps", []string{ccTerminal, "repo", "GYST"}},
		{Action{ActionRepo, "ZZ9"}, "Repo — ZZ9", []string{ccTerminal, "repo", "ZZ9"}},
		{Action{ActionServer, ""}, "Server — jay-server", nil},
	}
	for _, c := range cases {
		exe, args := terminalArgv(c.a, cfg, tWT, tSSH, tPS)
		want := append([]string{"-w", "CommandCenter", "new-tab", "--title", c.title, "--suppressApplicationTitle", "--", tSSH,
			"-t", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "--", "jay-server"}, c.tail...)
		if exe != tWT || !reflect.DeepEqual(args, want) {
			t.Errorf("%+v:\n got %s %q\nwant %q", c.a, exe, args, want)
		}
		for _, s := range append([]string{exe}, args...) {
			if strings.ContainsAny(s, ";\"\n\r") {
				t.Errorf("%+v: arg %q has ; or a quote", c.a, s)
			}
		}
		for _, s := range args {
			if s == "-N" || strings.Contains(s, "BatchMode") {
				t.Errorf("%+v: %q must not be used for an interactive terminal", c.a, s)
			}
		}
	}
	// The host always comes from the config, after "--".
	_, args := terminalArgv(Action{ActionClaude, "SV"}, Config{Host: "box.lan", LocalPort: 1, RemotePort: 1}, tWT, tSSH, tPS)
	if args[len(args)-5] != "--" || args[len(args)-4] != "box.lan" {
		t.Fatalf("host: %q", args)
	}
}

func TestTerminalCommandLineWT(t *testing.T) {
	exe, args := terminalArgv(Action{ActionClaude, "SV"}, DefaultConfig(), tWT, tSSH, tPS)
	got := commandLine(exe, args)
	want := tWT + ` -w CommandCenter new-tab --title "Claude — SamVision" --suppressApplicationTitle -- ` + tSSH +
		` -t -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -- jay-server ` + ccTerminal + ` claude SV`
	if got != want {
		t.Fatalf("\n got %s\nwant %s", got, want)
	}
	if strings.Contains(got, ";") {
		t.Fatal("wt command line contains ;")
	}
}

func TestTerminalArgvPowerShell(t *testing.T) {
	exe, args := terminalArgv(Action{ActionClaude, "SV"}, DefaultConfig(), "", tSSH, tPS)
	wantCmd := `$Host.UI.RawUI.WindowTitle='Claude — SamVision'; & '` + tSSH +
		`' '-t' '-o' 'ServerAliveInterval=30' '-o' 'ServerAliveCountMax=3' '--' 'jay-server' '` + ccTerminal + `' 'claude' 'SV'`
	if exe != tPS || !reflect.DeepEqual(args, []string{"-NoLogo", "-NoExit", "-Command", wantCmd}) {
		t.Fatalf("got %s %q", exe, args)
	}
	if got, want := commandLine(exe, args), tPS+` -NoLogo -NoExit -Command "`+wantCmd+`"`; got != want {
		t.Fatalf("\n got %s\nwant %s", got, want)
	}

	// ssh in a folder with a space and an apostrophe.
	odd := `C:\Program Files\Jay's Tools\ssh.exe`
	_, args = terminalArgv(Action{ActionServer, ""}, DefaultConfig(), "", odd, tPS)
	wantCmd = `$Host.UI.RawUI.WindowTitle='Server — jay-server'; & 'C:\Program Files\Jay''s Tools\ssh.exe'` +
		` '-t' '-o' 'ServerAliveInterval=30' '-o' 'ServerAliveCountMax=3' '--' 'jay-server'`
	if args[3] != wantCmd {
		t.Fatalf("\n got %s\nwant %s", args[3], wantCmd)
	}
	if got, want := commandLine(tPS, args), tPS+` -NoLogo -NoExit -Command "`+wantCmd+`"`; got != want {
		t.Fatalf("\n got %s\nwant %s", got, want)
	}
}

func TestPSQuote(t *testing.T) {
	for in, want := range map[string]string{
		"":          "''",
		"a b":       "'a b'",
		"it's":      "'it''s'",
		"it\u2019s": "'it\u2019\u2019s'",
		"$x;`y`":    "'$x;`y`'",
	} {
		if got := psQuote(in); got != want {
			t.Errorf("%q: got %q want %q", in, got, want)
		}
	}
}

func TestEscapeArg(t *testing.T) {
	for in, want := range map[string]string{
		"":             `""`,
		"plain":        "plain",
		"a b":          `"a b"`,
		`C:\x\y`:       `C:\x\y`,
		`a"b`:          `a\"b`,
		`C:\a b\`:      `"C:\a b\\"`,
		`say "hi" now`: `"say \"hi\" now"`,
		`back\\"quote`: `back\\\\\"quote`,
		"tab\there":    "\"tab\there\"",
		"Claude — Sam": `"Claude — Sam"`,
	} {
		if got := escapeArg(in); got != want {
			t.Errorf("%q: got %s want %s", in, got, want)
		}
	}
	if got := commandLine(`C:\Program Files\x.exe`, []string{"a"}); got != `"C:\Program Files\x.exe" a` {
		t.Errorf("exe with space: %s", got)
	}
}

func TestFindWT(t *testing.T) {
	env := func(k string) string { return map[string]string{"LOCALAPPDATA": `C:\Users\jay\AppData\Local`}[k] }
	noPath := func(string) (string, error) { return "", errNoAnswer }
	if got := FindWT(env, func(p string) bool { return p == tWT }, noPath); got != tWT {
		t.Fatalf("alias: %q", got)
	}
	onPath := func(string) (string, error) { return `D:\wt\wt.exe`, nil }
	if got := FindWT(env, func(string) bool { return false }, onPath); got != `D:\wt\wt.exe` {
		t.Fatalf("PATH: %q", got)
	}
	if got := FindWT(env, func(string) bool { return false }, noPath); got != "" {
		t.Fatalf("none: %q", got)
	}
}

func TestProtocolRegistry(t *testing.T) {
	exe := `C:\Users\jay\Apps\CommandCenter.exe`
	got, err := protocolRegistry(exe)
	if err != nil {
		t.Fatal(err)
	}
	want := []regValue{
		{`Software\Classes\commandcenter`, "", "URL:Command Center"},
		{`Software\Classes\commandcenter`, "URL Protocol", ""},
		{`Software\Classes\commandcenter\DefaultIcon`, "", `"C:\Users\jay\Apps\CommandCenter.exe",0`},
		{`Software\Classes\commandcenter\shell\open\command`, "", `"C:\Users\jay\Apps\CommandCenter.exe" "%1"`},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %q", got)
	}
	if _, err := protocolRegistry(`\\server\share\CommandCenter.exe`); err != nil {
		t.Fatalf("UNC: %v", err)
	}
	for _, bad := range []string{"", "CommandCenter.exe", `Apps\CommandCenter.exe`, `C:\a"b.exe`, "/usr/bin/x", "C:x.exe"} {
		if _, err := protocolRegistry(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
}

// Action mode starts exactly one terminal and nothing else: no mutex, no
// ssh tunnel, no browser.
func TestRunActionStartsOnlyATerminal(t *testing.T) {
	f := newFake()
	f.exists[tWT] = true
	if code := runAction(f, &logger{}, "commandcenter://terminal/claude?project=SV"); code != 0 {
		t.Fatalf("exit %d alerts %q", code, f.alerts)
	}
	want := []string{tWT, "-w", "CommandCenter", "new-tab", "--title", "Claude — SamVision", "--suppressApplicationTitle", "--", fakeSSH,
		"-t", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "--", "jay-server", ccTerminal, "claude", "SV"}
	if len(f.terminals) != 1 || !reflect.DeepEqual(f.terminals[0], want) || f.newConsole[0] {
		t.Fatalf("terminals %q console %v", f.terminals, f.newConsole)
	}
	if len(f.mutexes)+len(f.ssh)+len(f.browsers)+len(f.defaults)+len(f.alerts) != 0 {
		t.Fatalf("side effects: %q %d %q %q %q", f.mutexes, len(f.ssh), f.browsers, f.defaults, f.alerts)
	}
}

func TestRunActionPowerShellFallback(t *testing.T) {
	f := newFake()
	if code := runAction(f, &logger{}, "commandcenter://terminal/server"); code != 0 {
		t.Fatalf("exit %d alerts %q", code, f.alerts)
	}
	if len(f.terminals) != 1 || f.terminals[0][0] != tPS || !f.newConsole[0] {
		t.Fatalf("terminals %q console %v", f.terminals, f.newConsole)
	}
}

func TestRunActionRefusesBadLink(t *testing.T) {
	f := newFake()
	f.exists[tWT] = true
	if code := runAction(f, &logger{}, "commandcenter://terminal/claude?project=SV;calc"); code == 0 {
		t.Fatal("bad link accepted")
	}
	if len(f.terminals) != 0 || len(f.alerts) != 1 || !f.errAlert[0] ||
		!strings.HasPrefix(f.alerts[0], "Command Center can't open that terminal: ") {
		t.Fatalf("terminals %q alerts %q", f.terminals, f.alerts)
	}
}

func TestRunActionNoSSH(t *testing.T) {
	f := newFake()
	f.exists = map[string]bool{tWT: true}
	if code := runAction(f, &logger{}, "commandcenter://terminal/server"); code == 0 || len(f.terminals) != 0 || len(f.alerts) != 1 {
		t.Fatalf("code %d terminals %q alerts %q", code, f.terminals, f.alerts)
	}
}

func TestRunActionFallsBackWhenWTWillNotStart(t *testing.T) {
	f := newFake()
	f.exists[tWT] = true
	f.termFail = 1
	if code := runAction(f, &logger{}, "commandcenter://terminal/repo?project=GZ"); code != 0 {
		t.Fatalf("exit %d alerts %q", code, f.alerts)
	}
	if len(f.terminals) != 2 || f.terminals[0][0] != tWT || f.terminals[1][0] != tPS || !f.newConsole[1] {
		t.Fatalf("terminals %q console %v", f.terminals, f.newConsole)
	}
	if !strings.Contains(f.terminals[1][len(f.terminals[1])-1], "'repo' 'GZ'") {
		t.Fatalf("fallback command %q", f.terminals[1])
	}
}

package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"time"
)

// Platform is everything OS-specific. platform_windows.go is the real one;
// platform_other.go only exists so the package builds and tests on Linux.
type Platform interface {
	Getenv(string) string
	Exists(path string) bool
	LookPath(file string) (string, error)
	AppPath(exe string) string
	Alert(msg string, isError bool)
	StartSSH(path string, args []string, stderr io.Writer) (Proc, error) // hidden, inside the kill-on-close job
	StartBrowser(path string, args []string) (Proc, error)
	// StartTerminal starts a visible terminal that outlives the launcher (not
	// in the job). newConsole asks for a new console window (PowerShell).
	StartTerminal(path string, args []string, newConsole bool) error
	OpenDefault(url string) error
	// FirstInstance takes a per-user named mutex for the life of the process.
	// false means another launcher already holds it.
	FirstInstance(name string) bool
	// Tray shows a notification-area icon with m's menu and blocks until the
	// user picks Quit or stop closes (nil), or returns an error at once when
	// no icon could be shown.
	Tray(m TrayMenu, stop <-chan struct{}) error
}

// TrayMenu is the tray icon's tooltip and actions. Open, Reconnect and
// Terminal run on their own goroutine; they must not block the tray's message
// loop. A nil Terminal hides "Open server terminal".
type TrayMenu struct {
	Tip       string
	Open      func()
	Reconnect func()
	Terminal  func()
}

const title = "Command Center"

// app is one launcher run. The fields besides p and log exist so tests can
// replace the network probes and shorten the waits.
type app struct {
	p        Platform
	log      *logger
	classify func(port int) PortState
	probe    func(port int) bool
	// handoff: an Edge/Chrome that exits this fast handed the window to an
	// already-running instance of the same profile, so we cannot track it.
	handoff time.Duration
	// secondWait: how long a second launch waits for the first one's tunnel.
	secondWait time.Duration
	poll       time.Duration
	newTunnel  func(start func(*tailBuffer) (Proc, error), probe func() bool, log *logger) *tunnel
}

func newApp(p Platform, log *logger) *app {
	return &app{
		p: p, log: log,
		classify:   ClassifyPort,
		probe:      func(port int) bool { ok, _ := ProbeCCD(port); return ok },
		handoff:    5 * time.Second,
		secondWait: 25 * time.Second,
		poll:       500 * time.Millisecond,
		newTunnel:  newTunnel,
	}
}

func run(p Platform, log *logger) int { return newApp(p, log).run() }

func loadConfig(p Platform) (Config, string, error) {
	dir := AppDir(p.Getenv)
	if dir == "" {
		return DefaultConfig(), "", nil
	}
	path := winJoin(dir, "launcher.json")
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return DefaultConfig(), path, nil
	}
	if err != nil {
		return DefaultConfig(), path, err
	}
	defer f.Close()
	cfg, err := ParseConfig(f)
	return cfg, path, err
}

// openBrowser starts the first Edge/Chrome that exists. nil Proc means it fell
// back to the default browser (or nothing could be opened: err != nil).
func openBrowser(p Platform, url, profile string, log *logger) (Proc, error) {
	args := BrowserArgs(url, profile)
	for _, c := range BrowserCandidates(p.Getenv, p.AppPath) {
		if !p.Exists(c) {
			continue
		}
		b, err := p.StartBrowser(c, args)
		if err == nil {
			log.Printf("browser %s", c)
			return b, nil
		}
		log.Printf("browser %s failed: %v", c, err)
	}
	log.Printf("browser: default handler")
	return nil, p.OpenDefault(url)
}

// openDetached opens a window nobody waits on (reuse, second launch, tray).
func (a *app) openDetached(url, profile string) error {
	b, err := openBrowser(a.p, url, profile, a.log)
	if b != nil {
		go b.Wait() // reap only; its lifetime does not matter here
	}
	return err
}

// MutexName is per user (Local\) and per port.
func MutexName(port int) string { return fmt.Sprintf(`Local\CommandCenterLauncher-%d`, port) }

func (a *app) run() int {
	p := a.p
	cfg, cfgPath, err := loadConfig(p)
	if err != nil {
		p.Alert(fmt.Sprintf("The settings file has a problem:\n%s\n\n%v\n\nFix or delete it, then start Command Center again.", cfgPath, err), true)
		return 2
	}
	url := fmt.Sprintf("http://127.0.0.1:%d", cfg.LocalPort)
	profile := winJoin(AppDir(p.Getenv), "Browser")

	if !p.FirstInstance(MutexName(cfg.LocalPort)) {
		return a.secondLaunch(cfg, url, profile)
	}

	switch a.classify(cfg.LocalPort) {
	case PortCCD:
		a.log.Printf("reuse: Command Center already answers on %d", cfg.LocalPort)
		if err := a.openDetached(url, profile); err != nil {
			p.Alert("Command Center is reachable at "+url+" but no browser could be opened.", true)
			return 1
		}
		return 0
	case PortForeign:
		a.log.Printf("port %d busy (not ccd)", cfg.LocalPort)
		p.Alert(fmt.Sprintf("Port %d is in use by another program, so Command Center cannot open its tunnel there.\n\nClose that program and try again.", cfg.LocalPort), true)
		return 1
	}

	sshPath, ok := FindSSH(p.Getenv, p.Exists, p.LookPath)
	if !ok {
		p.Alert("The Windows OpenSSH client (ssh.exe) was not found.\n\nInstall it from Settings > System > Optional features > OpenSSH Client, then try again.", true)
		return 1
	}
	args := SSHArgs(cfg)
	t := a.newTunnel(
		func(stderr *tailBuffer) (Proc, error) { return p.StartSSH(sshPath, args, stderr) },
		func() bool { return a.probe(cfg.LocalPort) },
		a.log,
	)
	a.log.Printf("ssh %s -> %s:%d", sshPath, cfg.Host, cfg.RemotePort)
	if err := t.Open(); err != nil {
		a.log.Printf("open failed: %v", err)
		t.Close()
		p.Alert(openFailure(cfg, err), true)
		return 1
	}

	stop := make(chan struct{})
	gaveUp := make(chan error, 1)
	go func() { gaveUp <- t.Supervise(stop) }()
	supervised := true
	// shutdown stops the supervisor first, then kills our ssh, and waits for
	// the supervisor so no reconnect can start an ssh after we return.
	shutdown := func() {
		close(stop)
		t.Close()
		if supervised {
			select {
			case <-gaveUp:
			case <-time.After(5 * time.Second):
				a.log.Printf("supervisor did not stop in 5s")
			}
		}
	}

	b, err := openBrowser(p, url, profile, a.log)
	if err != nil {
		shutdown()
		p.Alert("The tunnel is up, but no browser could be opened. Visit "+url+" yourself.", true)
		return 1
	}

	trayStop := make(chan struct{})
	closed := make(chan struct{})
	go func() {
		defer close(closed)
		if b != nil {
			started := time.Now()
			_ = b.Wait()
			if time.Since(started) >= a.handoff {
				a.log.Printf("browser closed; stopping tunnel")
				return
			}
			a.log.Printf("browser handed off to an existing window")
		}
		a.waitForUser(cfg, url, profile, t, trayStop)
	}()

	select {
	case <-closed:
	case err := <-gaveUp:
		supervised = false
		close(trayStop) // removes the tray icon, if one is shown
		select {
		case <-closed:
		case <-time.After(2 * time.Second): // a MessageBox stays until we exit
		}
		shutdown()
		if err != nil {
			a.log.Printf("gave up: %v", err)
			p.Alert("Command Center "+err.Error(), true)
			return 1
		}
		return 0
	}
	shutdown()
	return 0
}

// waitForUser runs when we cannot see the window close (default browser, or
// Edge handed the window to a running instance): a tray icon whose Quit stops
// the tunnel, or, if no tray icon can be shown, the old "Click OK" box.
func (a *app) waitForUser(cfg Config, url, profile string, t *tunnel, stop <-chan struct{}) {
	err := a.p.Tray(TrayMenu{
		Tip: "Command Center (tunnel to " + cfg.Host + ")",
		Open: func() {
			if err := a.openDetached(url, profile); err != nil {
				a.log.Printf("tray open: %v", err)
			}
		},
		Reconnect: func() {
			a.log.Printf("tray: reconnect")
			t.Reconnect()
		},
		Terminal: func() {
			if err := openTerminal(a.p, a.log, cfg, Action{Kind: ActionServer}); err != nil {
				a.log.Printf("tray terminal: %v", err)
				a.p.Alert(actionFail+err.Error(), true)
			}
		},
	}, stop)
	if err == nil {
		a.log.Printf("tray: quit")
		return
	}
	a.log.Printf("tray unavailable: %v", err)
	a.p.Alert("Command Center is running.\n\nClick OK to stop the tunnel.", false)
}

// secondLaunch: another launcher holds the mutex, so it owns (or is opening)
// the tunnel. Open a window on it instead of starting a second ssh.
func (a *app) secondLaunch(cfg Config, url, profile string) int {
	a.log.Printf("another launcher is running; opening a window only")
	deadline := time.Now().Add(a.secondWait)
	for !a.probe(cfg.LocalPort) {
		if time.Now().After(deadline) {
			a.p.Alert(fmt.Sprintf("Command Center is already starting, but it has not answered for %d seconds.\n\nWait for it, or close the other Command Center (its tray icon or message box) and try again.",
				int(a.secondWait/time.Second)), true)
			return 1
		}
		time.Sleep(a.poll)
	}
	if err := a.openDetached(url, profile); err != nil {
		a.p.Alert("Command Center is reachable at "+url+" but no browser could be opened.", true)
		return 1
	}
	return 0
}

func openFailure(cfg Config, err error) string {
	var se *sshExitError
	switch {
	case errors.As(err, &se):
		msg := fmt.Sprintf("Could not connect to %s.\n\n", cfg.Host)
		if se.line != "" {
			msg += "ssh said: " + se.line + "\n\n"
		}
		return msg + fmt.Sprintf("Check that \"ssh %s\" works in a terminal without asking anything.", cfg.Host)
	case errors.Is(err, errNoAnswer):
		return fmt.Sprintf("Connected to %s, but Command Center did not answer within 20 seconds.\n\nIs the ccd service running on the server?", cfg.Host)
	default:
		return "Could not start the tunnel: " + err.Error()
	}
}

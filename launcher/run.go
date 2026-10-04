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
	OpenDefault(url string) error
}

const title = "Command Center"

// browserHandoff: an Edge/Chrome that exits this fast handed the window to an
// already-running instance of the same profile, so we cannot track it.
const browserHandoff = 5 * time.Second

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

func run(p Platform, log *logger) int {
	cfg, cfgPath, err := loadConfig(p)
	if err != nil {
		p.Alert(fmt.Sprintf("The settings file has a problem:\n%s\n\n%v\n\nFix or delete it, then start Command Center again.", cfgPath, err), true)
		return 2
	}
	url := fmt.Sprintf("http://127.0.0.1:%d", cfg.LocalPort)
	profile := winJoin(AppDir(p.Getenv), "Browser")

	switch ClassifyPort(cfg.LocalPort) {
	case PortCCD:
		log.Printf("reuse: Command Center already answers on %d", cfg.LocalPort)
		if _, err := openBrowser(p, url, profile, log); err != nil {
			p.Alert("Command Center is reachable at "+url+" but no browser could be opened.", true)
			return 1
		}
		return 0
	case PortForeign:
		log.Printf("port %d busy (not ccd)", cfg.LocalPort)
		p.Alert(fmt.Sprintf("Port %d is in use by another program, so Command Center cannot open its tunnel there.\n\nClose that program and try again.", cfg.LocalPort), true)
		return 1
	}

	sshPath, ok := FindSSH(p.Getenv, p.Exists, p.LookPath)
	if !ok {
		p.Alert("The Windows OpenSSH client (ssh.exe) was not found.\n\nInstall it from Settings > System > Optional features > OpenSSH Client, then try again.", true)
		return 1
	}
	args := SSHArgs(cfg)
	t := newTunnel(
		func(stderr *tailBuffer) (Proc, error) { return p.StartSSH(sshPath, args, stderr) },
		func() bool { ok, _ := ProbeCCD(cfg.LocalPort); return ok },
		log,
	)
	log.Printf("ssh %s -> %s:%d", sshPath, cfg.Host, cfg.RemotePort)
	if err := t.Open(); err != nil {
		log.Printf("open failed: %v", err)
		p.Alert(openFailure(cfg, err), true)
		return 1
	}
	defer t.Close()

	stop := make(chan struct{})
	gaveUp := make(chan error, 1)
	go func() { gaveUp <- t.Supervise(stop) }()

	closed := make(chan struct{})
	b, err := openBrowser(p, url, profile, log)
	if err != nil {
		close(stop)
		p.Alert("The tunnel is up, but no browser could be opened. Visit "+url+" yourself.", true)
		return 1
	}
	waitBox := func() {
		p.Alert("Command Center is running.\n\nClick OK to stop the tunnel.", false)
	}
	go func() {
		defer close(closed)
		if b == nil {
			waitBox()
			return
		}
		started := time.Now()
		_ = b.Wait()
		if time.Since(started) < browserHandoff {
			log.Printf("browser handed off to an existing window")
			waitBox()
		}
	}()

	select {
	case <-closed:
		log.Printf("browser closed; stopping tunnel")
	case err := <-gaveUp:
		if err != nil {
			log.Printf("gave up: %v", err)
			p.Alert("Command Center "+err.Error(), true)
			close(stop)
			return 1
		}
	}
	close(stop)
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

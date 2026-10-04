// CommandCenter.exe: opens Command Center on Windows.
//
// It reuses a Command Center that already answers on 127.0.0.1:7777, or starts
// a hidden "ssh -N -L 7777:127.0.0.1:7777 jay-server", waits for ccd's health,
// opens Edge/Chrome as an app window, and stops that ssh when the window closes.
// It carries and reads no credentials; ssh uses Jay's existing key setup.
package main

import (
	"os"
	"path/filepath"
)

var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	p := newPlatform()
	log := openLog(logPath(p))
	args := os.Args[1:]
	var code int
	if hasActionURI(args) {
		// Native terminal action: no mutex, no tunnel, no browser.
		log.Printf("action version=%s commit=%s", version, commit)
		if len(args) != 1 {
			p.Alert(actionFail+"expected exactly one commandcenter: link.", true)
			code = 2
		} else {
			code = runAction(p, log, args[0])
		}
	} else {
		log.Printf("start version=%s commit=%s", version, commit)
		if len(args) == 0 {
			registerSelf(log)
		}
		code = run(p, log)
	}
	log.Printf("exit %d", code)
	log.Close()
	p.Shutdown() // closes the job: any ssh we started dies with us
	os.Exit(code)
}

func logPath(p Platform) string {
	dir := AppDir(p.Getenv)
	if dir == "" || os.MkdirAll(dir, 0o700) != nil {
		return ""
	}
	return winJoin(dir, "launcher.log")
}

// registerSelf (re)points the per-user commandcenter: protocol at this exe.
// A failure is only logged: the launcher works without it.
func registerSelf(log *logger) {
	exe, err := os.Executable()
	if err == nil {
		exe, err = filepath.Abs(exe)
	}
	if err != nil {
		log.Printf("protocol: no exe path: %v", err)
		return
	}
	vals, err := protocolRegistry(exe)
	if err == nil {
		err = registerProtocol(vals)
	}
	if err != nil {
		log.Printf("protocol registration failed: %v", err)
	}
}

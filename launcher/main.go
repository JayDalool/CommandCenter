// CommandCenter.exe: opens Command Center on Windows.
//
// It reuses a Command Center that already answers on 127.0.0.1:7777, or starts
// a hidden "ssh -N -L 7777:127.0.0.1:7777 jay-server", waits for ccd's health,
// opens Edge/Chrome as an app window, and stops that ssh when the window closes.
// It carries and reads no credentials; ssh uses Jay's existing key setup.
package main

import "os"

var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	p := newPlatform()
	log := openLog(logPath(p))
	log.Printf("start version=%s commit=%s", version, commit)
	code := run(p, log)
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

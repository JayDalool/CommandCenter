package main

import "fmt"

// SSHArgs builds the tunnel command line. The host is validated before this
// runs and also sits after "--", so it can never be read as an ssh option.
// BatchMode makes ssh fail fast instead of waiting on a prompt nobody can see.
func SSHArgs(c Config) []string {
	return []string{
		"-N", "-T",
		"-o", "BatchMode=yes",
		"-o", "ExitOnForwardFailure=yes",
		"-o", "ServerAliveInterval=30",
		"-o", "ServerAliveCountMax=3",
		"-o", "LogLevel=ERROR",
		"-L", fmt.Sprintf("%d:127.0.0.1:%d", c.LocalPort, c.RemotePort),
		"--", c.Host,
	}
}

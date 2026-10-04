//go:build !windows

package main

// Not a supported target. This exists only so `go vet` and the pure-logic
// tests run on Linux CI; the real behaviour lives in platform_windows.go.

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
)

type osPlatform struct{}

func newPlatform() *osPlatform { return &osPlatform{} }

func (p *osPlatform) Shutdown()                            {}
func (p *osPlatform) Getenv(k string) string               { return os.Getenv(k) }
func (p *osPlatform) LookPath(file string) (string, error) { return exec.LookPath(file) }
func (p *osPlatform) AppPath(string) string                { return "" }
func (p *osPlatform) Alert(msg string, _ bool)             { fmt.Fprintln(os.Stderr, msg) }

func (p *osPlatform) Exists(path string) bool {
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}

func (p *osPlatform) StartSSH(string, []string, io.Writer) (Proc, error) {
	return nil, errors.New("only supported on Windows")
}

func (p *osPlatform) StartBrowser(string, []string) (Proc, error) {
	return nil, errors.New("only supported on Windows")
}

func (p *osPlatform) StartTerminal(string, []string, bool) error {
	return errors.New("only supported on Windows")
}

func registerProtocol([]regValue) error { return errors.New("only supported on Windows") }

func (p *osPlatform) OpenDefault(string) error { return errors.New("only supported on Windows") }

func (p *osPlatform) FirstInstance(string) bool { return true }

func (p *osPlatform) Tray(TrayMenu, <-chan struct{}) error {
	return errors.New("only supported on Windows")
}

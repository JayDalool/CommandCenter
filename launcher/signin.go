package main

// SSH sign-in (server/ccd/signin.py). The launcher already proves it is Jay: its tunnel is an SSH key
// login. Over that same login it runs the fixed server helper scripts/cc-session, which reads the
// developer token as jay and asks ccd for a one-time, two-minute code. The browser opens
// http://127.0.0.1:<port>/#/?signin=<code>, and the page trades the code for the ccd token and a
// day-long Developer session: nothing to paste, nothing to unlock.
//
// The launcher never sees a token: it only carries the code from ssh's stdout to the URL. A code
// that does not look like one is dropped, and any failure falls back to the plain URL (the page then
// asks as before), so sign-in can never stop Command Center from opening.

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

const ccSession = "/srv/server/repos/CommandCenter/scripts/cc-session"

var signinCodeRE = regexp.MustCompile(`^[A-Za-z0-9_-]{20,128}$`)

// SigninArgs: a non-interactive ssh that runs only the fixed helper. The host sits after "--".
func SigninArgs(c Config) []string {
	args := []string{
		"-T",
		"-o", "BatchMode=yes",
		"-o", "ConnectTimeout=10",
		"-o", "LogLevel=ERROR",
		"--", c.Host, ccSession,
	}
	if c.RemotePort != 7777 {
		args = append(args, "--port", fmt.Sprint(c.RemotePort))
	}
	return args
}

// ParseSigninCode accepts exactly one code line.
func ParseSigninCode(out []byte) (string, error) {
	code := strings.TrimSpace(string(out))
	if !signinCodeRE.MatchString(code) {
		return "", errors.New("the server did not answer with a sign-in code")
	}
	return code, nil
}

// SigninURL is base with the code in the fragment (never sent to a server, removed by the page at once).
func SigninURL(base, code string) string { return base + "/#/?signin=" + code }

// signedURL asks the server for a code; on any failure it returns base unchanged (logged).
func (a *app) signedURL(cfg Config, base string) string {
	if a.signin == nil {
		return base
	}
	code, err := a.signin(cfg)
	if err != nil {
		a.log.Printf("ssh sign-in skipped: %v", err)
		return base
	}
	a.log.Printf("ssh sign-in code issued")
	return SigninURL(base, code)
}

// sshSignin runs cc-session over ssh with a time limit.
func sshSignin(p Platform) func(Config) (string, error) {
	return func(cfg Config) (string, error) {
		path, ok := FindSSH(p.Getenv, p.Exists, p.LookPath)
		if !ok {
			return "", errors.New("ssh.exe not found")
		}
		type res struct {
			out []byte
			err error
		}
		ch := make(chan res, 1)
		go func() { o, e := p.Output(path, SigninArgs(cfg)); ch <- res{o, e} }()
		select {
		case r := <-ch:
			if r.err != nil {
				return "", fmt.Errorf("cc-session failed: %v", r.err)
			}
			return ParseSigninCode(r.out)
		case <-time.After(20 * time.Second):
			return "", errors.New("cc-session did not answer in 20 s")
		}
	}
}

package main

import "strings"

// winJoin joins Windows path parts with backslashes on every OS, so the path
// logic is identical in Linux tests and on Windows.
func winJoin(parts ...string) string {
	out := ""
	for _, p := range parts {
		if p == "" {
			continue
		}
		if out == "" {
			out = strings.TrimRight(p, `\/`)
			continue
		}
		out += `\` + strings.Trim(p, `\/`)
	}
	return out
}

// AppDir is %LOCALAPPDATA%\CommandCenter (config, log, browser profile).
func AppDir(getenv func(string) string) string {
	base := getenv("LOCALAPPDATA")
	if base == "" {
		return ""
	}
	return winJoin(base, "CommandCenter")
}

// FindSSH prefers the Windows built-in OpenSSH client, then ssh.exe on PATH.
func FindSSH(getenv func(string) string, exists func(string) bool, lookPath func(string) (string, error)) (string, bool) {
	root := getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	builtin := winJoin(root, "System32", "OpenSSH", "ssh.exe")
	if exists(builtin) {
		return builtin, true
	}
	if p, err := lookPath("ssh.exe"); err == nil && p != "" {
		return p, true
	}
	return "", false
}

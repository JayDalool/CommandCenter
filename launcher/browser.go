package main

// BrowserCandidates lists Edge then Chrome install locations, most likely first.
// appPath looks up the "App Paths" registry entry (returns "" when absent).
func BrowserCandidates(getenv func(string) string, appPath func(exe string) string) []string {
	var out []string
	seen := map[string]bool{}
	add := func(p string) {
		if p != "" && !seen[p] {
			seen[p] = true
			out = append(out, p)
		}
	}
	under := func(envVar string, rel ...string) {
		if base := getenv(envVar); base != "" {
			add(winJoin(append([]string{base}, rel...)...))
		}
	}
	under("ProgramFiles(x86)", "Microsoft", "Edge", "Application", "msedge.exe")
	under("ProgramFiles", "Microsoft", "Edge", "Application", "msedge.exe")
	add(appPath("msedge.exe"))
	under("ProgramFiles", "Google", "Chrome", "Application", "chrome.exe")
	under("ProgramFiles(x86)", "Google", "Chrome", "Application", "chrome.exe")
	under("LOCALAPPDATA", "Google", "Chrome", "Application", "chrome.exe")
	add(appPath("chrome.exe"))
	return out
}

// BrowserArgs opens the UI as an app window in a dedicated profile, so the
// browser process we start lives exactly as long as Command Center's windows.
func BrowserArgs(url, profileDir string) []string {
	return []string{
		"--app=" + url,
		"--user-data-dir=" + profileDir,
		"--no-first-run",
		"--no-default-browser-check",
	}
}

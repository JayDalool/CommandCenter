package main

import (
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

const (
	fakeSSH    = `C:\Windows\System32\OpenSSH\ssh.exe`
	fakeEdge86 = `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
	fakeEdge   = `C:\Program Files\Microsoft\Edge\Application\msedge.exe`
	fakeChrome = `C:\Program Files\Google\Chrome\Application\chrome.exe`
)

// fakePlatform records what run() asked the OS to do.
type fakePlatform struct {
	mu          sync.Mutex
	exists      map[string]bool
	failBrowser map[string]bool
	first       bool
	browserExit bool // the browser process ends at once (hand-off)

	alerts   []string
	errAlert []bool
	ssh      []*fakeProc
	sshArgs  [][]string
	browsers []string
	browser  []*fakeProc
	defaults []string
	trays    int
	mutexes  []string

	terminals  [][]string
	termFail   int // fail this many StartTerminal calls first
	newConsole []bool

	sshStart func(n int, stderr io.Writer, p *fakeProc) // optional per-start behaviour
	tray     func(m TrayMenu, stop <-chan struct{}) error
}

func newFake() *fakePlatform {
	return &fakePlatform{
		exists: map[string]bool{fakeSSH: true, fakeEdge86: true},
		first:  true,
	}
}

func (f *fakePlatform) Getenv(k string) string {
	return map[string]string{
		"SystemRoot":        `C:\Windows`,
		"LOCALAPPDATA":      `C:\Users\jay\AppData\Local`,
		"ProgramFiles":      `C:\Program Files`,
		"ProgramFiles(x86)": `C:\Program Files (x86)`,
	}[k]
}
func (f *fakePlatform) Exists(p string) bool            { return f.exists[p] }
func (f *fakePlatform) LookPath(string) (string, error) { return "", errors.New("not on PATH") }
func (f *fakePlatform) AppPath(string) string           { return "" }
func (f *fakePlatform) FirstInstance(name string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.mutexes = append(f.mutexes, name)
	return f.first
}

func (f *fakePlatform) Alert(msg string, isError bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.alerts = append(f.alerts, msg)
	f.errAlert = append(f.errAlert, isError)
}

func (f *fakePlatform) StartSSH(path string, args []string, stderr io.Writer) (Proc, error) {
	f.mu.Lock()
	p := newFakeProc()
	f.ssh = append(f.ssh, p)
	f.sshArgs = append(f.sshArgs, append([]string{path}, args...))
	n, hook := len(f.ssh), f.sshStart
	f.mu.Unlock()
	if hook != nil {
		hook(n, stderr, p)
	}
	return p, nil
}

func (f *fakePlatform) StartBrowser(path string, args []string) (Proc, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.browsers = append(f.browsers, path+" "+strings.Join(args, " "))
	if f.failBrowser[path] {
		return nil, errors.New("cannot start")
	}
	p := newFakeProc()
	if f.browserExit {
		p.end()
	}
	f.browser = append(f.browser, p)
	return p, nil
}

func (f *fakePlatform) StartTerminal(path string, args []string, newConsole bool) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.terminals = append(f.terminals, append([]string{path}, args...))
	f.newConsole = append(f.newConsole, newConsole)
	if f.termFail > 0 {
		f.termFail--
		return errors.New("wt would not start")
	}
	return nil
}

func (f *fakePlatform) OpenDefault(url string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.defaults = append(f.defaults, url)
	return nil
}

func (f *fakePlatform) Tray(m TrayMenu, stop <-chan struct{}) error {
	f.mu.Lock()
	f.trays++
	tray := f.tray
	f.mu.Unlock()
	if tray == nil {
		return errors.New("no tray in this test")
	}
	return tray(m, stop)
}

func (f *fakePlatform) sshAt(i int) *fakeProc {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.ssh[i]
}

func (f *fakePlatform) sshCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.ssh)
}

func (f *fakePlatform) waitSSH(t *testing.T, n int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for f.sshCount() < n {
		if time.Now().After(deadline) {
			t.Fatalf("waited for %d ssh starts, got %d", n, f.sshCount())
		}
		time.Sleep(time.Millisecond)
	}
}

// assertAllSSHKilled: every ssh we started is dead, and no more start later.
func (f *fakePlatform) assertAllSSHKilled(t *testing.T) {
	t.Helper()
	n := f.sshCount()
	time.Sleep(30 * time.Millisecond)
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.ssh) != n {
		t.Fatalf("ssh started after run returned (%d -> %d)", n, len(f.ssh))
	}
	for i, p := range f.ssh {
		select {
		case <-p.exit:
		default:
			t.Fatalf("ssh #%d still running", i+1)
		}
	}
}

func testApp(f *fakePlatform, state PortState, healthy func() bool) *app {
	a := newApp(f, &logger{})
	a.classify = func(int) PortState { return state }
	a.probe = func(int) bool { return healthy() }
	a.handoff = 0 // every browser exit counts as "window closed"
	a.secondWait = 50 * time.Millisecond
	a.poll = time.Millisecond
	mk := a.newTunnel
	a.newTunnel = func(s func(*tailBuffer) (Proc, error), p func() bool, l *logger) *tunnel {
		t := mk(s, p, l)
		t.poll = time.Millisecond
		t.timeout = 200 * time.Millisecond
		t.after = func(d time.Duration) <-chan time.Time { // backoff waits are instant
			if d == t.timeout {
				return time.After(d)
			}
			c := make(chan time.Time, 1)
			c <- time.Now()
			return c
		}
		return t
	}
	return a
}

func always(v bool) func() bool { return func() bool { return v } }

func runAsync(a *app) chan int {
	c := make(chan int, 1)
	go func() { c <- a.run() }()
	return c
}

func waitExit(t *testing.T, c chan int) int {
	t.Helper()
	select {
	case code := <-c:
		return code
	case <-time.After(5 * time.Second):
		t.Fatal("run did not return")
		return -1
	}
}

func TestRunReusesHealthyTunnel(t *testing.T) {
	f := newFake()
	if code := testApp(f, PortCCD, always(true)).run(); code != 0 {
		t.Fatalf("exit %d", code)
	}
	if len(f.ssh) != 0 || len(f.alerts) != 0 {
		t.Fatalf("ssh %d alerts %q", len(f.ssh), f.alerts)
	}
	if len(f.browsers) != 1 || !strings.HasPrefix(f.browsers[0], fakeEdge86+" --app=http://127.0.0.1:7777 ") {
		t.Fatalf("browsers %q", f.browsers)
	}
	if len(f.mutexes) != 1 || f.mutexes[0] != `Local\CommandCenterLauncher-7777` {
		t.Fatalf("mutex %q", f.mutexes)
	}
}

func TestRunForeignPortDialog(t *testing.T) {
	f := newFake()
	if code := testApp(f, PortForeign, always(false)).run(); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if len(f.alerts) != 1 || !f.errAlert[0] || !strings.Contains(f.alerts[0], "Port 7777 is in use by another program") {
		t.Fatalf("alerts %q", f.alerts)
	}
	if len(f.ssh) != 0 || len(f.browsers) != 0 || len(f.defaults) != 0 {
		t.Fatal("started something despite a foreign port")
	}
}

func TestRunNoSSHClient(t *testing.T) {
	f := newFake()
	delete(f.exists, fakeSSH)
	if code := testApp(f, PortFree, always(true)).run(); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if len(f.alerts) != 1 || !strings.Contains(f.alerts[0], "OpenSSH client") {
		t.Fatalf("alerts %q", f.alerts)
	}
}

func TestRunConnectFailureShowsSSHReason(t *testing.T) {
	f := newFake()
	f.sshStart = func(_ int, stderr io.Writer, p *fakeProc) {
		stderr.Write([]byte("jay-server: Permission denied (publickey).\r\n"))
		p.end()
	}
	if code := testApp(f, PortFree, always(false)).run(); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if len(f.alerts) != 1 || !strings.Contains(f.alerts[0], "ssh said: jay-server: Permission denied (publickey).") {
		t.Fatalf("alerts %q", f.alerts)
	}
	if len(f.browsers) != 0 {
		t.Fatal("opened a browser without a tunnel")
	}
	f.assertAllSSHKilled(t)
}

func TestRunHealthTimeoutKillsSSH(t *testing.T) {
	f := newFake()
	a := testApp(f, PortFree, always(false))
	if code := a.run(); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if len(f.alerts) != 1 || !strings.Contains(f.alerts[0], "did not answer within 20 seconds") {
		t.Fatalf("alerts %q", f.alerts)
	}
	f.assertAllSSHKilled(t)
}

// Edge window opens, ssh drops once and is restarted, window closes: the
// tunnel stops, and only ssh processes we started were ever killed.
func TestRunWindowCloseStopsTunnelAfterReconnect(t *testing.T) {
	f := newFake()
	done := runAsync(testApp(f, PortFree, always(true)))
	f.waitSSH(t, 1)
	deadline := time.Now().Add(5 * time.Second)
	for {
		f.mu.Lock()
		n := len(f.browser)
		f.mu.Unlock()
		if n == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("no browser")
		}
		time.Sleep(time.Millisecond)
	}
	f.sshAt(0).end() // network blip
	f.waitSSH(t, 2)
	f.mu.Lock()
	b := f.browser[0]
	f.mu.Unlock()
	b.end() // user closes the window
	if code := waitExit(t, done); code != 0 {
		t.Fatalf("exit %d", code)
	}
	f.assertAllSSHKilled(t)
	if f.ssh[1].kill != 1 {
		t.Fatalf("current ssh killed %d times", f.ssh[1].kill)
	}
	if len(f.alerts) != 0 || f.trays != 0 {
		t.Fatalf("alerts %q trays %d", f.alerts, f.trays)
	}
	if got := strings.Join(f.sshArgs[0], " "); !strings.Contains(got, "-o BatchMode=yes") || !strings.HasSuffix(got, " -- jay-server") {
		t.Fatalf("ssh args %q", got)
	}
}

func TestOpenBrowserOrder(t *testing.T) {
	f := newFake()
	f.exists = map[string]bool{fakeEdge86: true, fakeEdge: true, fakeChrome: true}
	f.failBrowser = map[string]bool{fakeEdge86: true, fakeEdge: true}
	b, err := openBrowser(f, "http://127.0.0.1:7777", `C:\p`, &logger{})
	if err != nil || b == nil {
		t.Fatalf("%v %v", b, err)
	}
	if len(f.browsers) != 3 || !strings.HasPrefix(f.browsers[2], fakeChrome+" ") {
		t.Fatalf("tried %q", f.browsers)
	}
	// nothing installed: default browser
	f = newFake()
	f.exists = map[string]bool{}
	b, err = openBrowser(f, "http://127.0.0.1:7777", `C:\p`, &logger{})
	if err != nil || b != nil || len(f.defaults) != 1 || f.defaults[0] != "http://127.0.0.1:7777" {
		t.Fatalf("%v %v %q", b, err, f.defaults)
	}
}

// No Edge/Chrome: default browser plus tray. Open re-opens the page,
// Reconnect restarts only our ssh, Quit stops it and exits.
func TestRunDefaultBrowserTray(t *testing.T) {
	f := newFake()
	f.exists = map[string]bool{fakeSSH: true}
	var tip string
	f.tray = func(m TrayMenu, stop <-chan struct{}) error {
		tip = m.Tip
		m.Open()
		m.Terminal()
		m.Reconnect()
		f.waitSSH(t, 2)
		return nil // Quit
	}
	code := waitExit(t, runAsync(testApp(f, PortFree, always(true))))
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	if tip != "Command Center (tunnel to jay-server)" {
		t.Fatalf("tip %q", tip)
	}
	if len(f.defaults) != 2 {
		t.Fatalf("default browser opened %d times", len(f.defaults))
	}
	// "Open server terminal": a plain login, nothing project-specific.
	if len(f.terminals) != 1 || !strings.HasSuffix(f.terminals[0][len(f.terminals[0])-1], "'-t' '-o' 'ServerAliveInterval=30' '-o' 'ServerAliveCountMax=3' '--' 'jay-server'") {
		t.Fatalf("tray terminal %q", f.terminals)
	}
	if len(f.ssh) != 2 || f.ssh[0].kill != 1 || f.ssh[1].kill != 1 {
		t.Fatalf("ssh %d", len(f.ssh))
	}
	if len(f.alerts) != 0 {
		t.Fatalf("alerts %q", f.alerts)
	}
	f.assertAllSSHKilled(t)
}

func TestRunNoTrayFallsBackToMessageBox(t *testing.T) {
	f := newFake()
	f.exists = map[string]bool{fakeSSH: true}
	if code := waitExit(t, runAsync(testApp(f, PortFree, always(true)))); code != 0 {
		t.Fatalf("exit %d", code)
	}
	if f.trays != 1 || len(f.alerts) != 1 || f.errAlert[0] || !strings.Contains(f.alerts[0], "Click OK to stop the tunnel") {
		t.Fatalf("trays %d alerts %q", f.trays, f.alerts)
	}
	f.assertAllSSHKilled(t)
}

// Edge exits at once (handed the window to a running Edge): we cannot see the
// window close, so the tray decides when to stop.
func TestRunBrowserHandoffUsesTray(t *testing.T) {
	f := newFake()
	f.browserExit = true
	quit := make(chan struct{})
	f.tray = func(m TrayMenu, stop <-chan struct{}) error { <-quit; return nil }
	a := testApp(f, PortFree, always(true))
	a.handoff = time.Hour
	done := runAsync(a)
	time.Sleep(20 * time.Millisecond)
	select {
	case <-done:
		t.Fatal("exited while the tray was still up")
	default:
	}
	close(quit)
	if code := waitExit(t, done); code != 0 {
		t.Fatalf("exit %d", code)
	}
	f.assertAllSSHKilled(t)
}

// ssh keeps failing while the tray is up: give up, remove the tray, say why.
func TestRunGivesUpAndClosesTray(t *testing.T) {
	f := newFake()
	f.exists = map[string]bool{fakeSSH: true}
	f.sshStart = func(n int, stderr io.Writer, p *fakeProc) {
		if n > 1 {
			stderr.Write([]byte("ssh: connect to host jay-server port 22: Connection timed out\n"))
			p.end()
		}
	}
	trayStopped := make(chan struct{})
	f.tray = func(m TrayMenu, stop <-chan struct{}) error {
		<-stop
		close(trayStopped)
		return nil
	}
	done := runAsync(testApp(f, PortFree, func() bool { return f.sshCount() == 1 }))
	f.waitSSH(t, 1)
	time.Sleep(10 * time.Millisecond)
	f.sshAt(0).end()
	if code := waitExit(t, done); code != 1 {
		t.Fatalf("exit %d", code)
	}
	<-trayStopped
	if len(f.ssh) != 1+maxReconnects {
		t.Fatalf("ssh starts %d", len(f.ssh))
	}
	if len(f.alerts) != 1 || !strings.Contains(f.alerts[0], "Connection timed out") {
		t.Fatalf("alerts %q", f.alerts)
	}
	f.assertAllSSHKilled(t)
}

func TestRunSecondLaunchOpensWindowOnly(t *testing.T) {
	f := newFake()
	f.first = false
	calls := 0
	code := testApp(f, PortFree, func() bool { calls++; return calls > 3 }).run()
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	if len(f.ssh) != 0 || len(f.browsers) != 1 || len(f.alerts) != 0 {
		t.Fatalf("ssh %d browsers %q alerts %q", len(f.ssh), f.browsers, f.alerts)
	}

	f = newFake()
	f.first = false
	if code := testApp(f, PortFree, always(false)).run(); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if len(f.ssh) != 0 || len(f.browsers) != 0 || len(f.alerts) != 1 || !strings.Contains(f.alerts[0], "already starting") {
		t.Fatalf("ssh %d browsers %q alerts %q", len(f.ssh), f.browsers, f.alerts)
	}
}

// A Close that lands while Supervise is starting a new ssh must not leave it running.
func TestTunnelCloseDuringStartKillsNewSSH(t *testing.T) {
	var started []*fakeProc
	var tn *tunnel
	tn = newTunnel(func(*tailBuffer) (Proc, error) {
		p := newFakeProc()
		started = append(started, p)
		tn.Close() // Close races in while ssh is starting
		return p, nil
	}, always(true), &logger{})
	if err := tn.Open(); !errors.Is(err, errClosed) {
		t.Fatalf("got %v", err)
	}
	if len(started) != 1 || started[0].kill != 1 {
		t.Fatal("ssh started during Close survived")
	}
	if err := tn.Open(); !errors.Is(err, errClosed) || len(started) != 1 {
		t.Fatal("Open after Close started ssh")
	}
}

// Reconnect during a backoff wait tries at once instead of waiting it out.
func TestTunnelReconnectSkipsBackoff(t *testing.T) {
	var mu sync.Mutex
	var procs []*fakeProc
	fail := true
	tn := newTunnel(func(*tailBuffer) (Proc, error) {
		mu.Lock()
		defer mu.Unlock()
		p := newFakeProc()
		procs = append(procs, p)
		if len(procs) > 1 && fail {
			p.end()
		}
		return p, nil
	}, func() bool { mu.Lock(); defer mu.Unlock(); return !fail || len(procs) == 1 }, &logger{})
	tn.poll = time.Millisecond
	waiting := make(chan struct{}, 10)
	tn.after = func(d time.Duration) <-chan time.Time {
		if d >= time.Second && d != tn.timeout {
			waiting <- struct{}{}
			return make(chan time.Time) // backoff never ends by itself
		}
		return time.After(d)
	}
	if err := tn.Open(); err != nil {
		t.Fatal(err)
	}
	stop := make(chan struct{})
	res := make(chan error, 1)
	go func() { res <- tn.Supervise(stop) }()
	procs[0].end()
	<-waiting // in the 2 s backoff
	mu.Lock()
	fail = false
	mu.Unlock()
	tn.Reconnect()
	deadline := time.Now().Add(5 * time.Second)
	for {
		mu.Lock()
		n := len(procs)
		mu.Unlock()
		if n == 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("Reconnect did not cut the backoff short")
		}
		time.Sleep(time.Millisecond)
	}
	close(stop)
	if err := <-res; err != nil {
		t.Fatal(err)
	}
	tn.Close()
}

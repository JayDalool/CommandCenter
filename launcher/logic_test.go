package main

import (
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestSSHArgs(t *testing.T) {
	got := SSHArgs(DefaultConfig())
	want := []string{"-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
		"-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "LogLevel=ERROR",
		"-L", "7777:127.0.0.1:7777", "--", "jay-server"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %q", got)
	}
	// host is always the final argument, after "--"
	c := Config{Host: "box.example", LocalPort: 9000, RemotePort: 9000}
	a := SSHArgs(c)
	if a[len(a)-2] != "--" || a[len(a)-1] != "box.example" || a[len(a)-3] != "9000:127.0.0.1:9000" {
		t.Fatalf("got %q", a)
	}
}

func TestParseConfig(t *testing.T) {
	ok := map[string]Config{
		``:                  DefaultConfig(),
		`{}`:                DefaultConfig(),
		`{"host":"my.box"}`: {Host: "my.box", LocalPort: 7777, RemotePort: 7777},
		`{"host":"a_b-c.d","localPort":8080,"remotePort":8080}`: {Host: "a_b-c.d", LocalPort: 8080, RemotePort: 8080},
	}
	for in, want := range ok {
		got, err := ParseConfig(strings.NewReader(in))
		if err != nil || got != want {
			t.Errorf("%q: got %+v, %v", in, got, err)
		}
	}
	bad := []string{
		`{"host":"-oProxyCommand=calc.exe"}`,
		`{"host":"-oProxyCommand"}`,
		`{"host":"-v"}`,
		`{"host":"jay-server -oProxyCommand=x"}`,
		`{"host":"jay;calc"}`,
		`{"host":"user@host"}`,
		`{"host":"a\nb"}`,
		`{"host":""}`,
		`{"host":"` + strings.Repeat("a", 254) + `"}`,
		`{"localPort":0,"remotePort":0}`,
		`{"localPort":65536,"remotePort":65536}`,
		`{"localPort":-1}`,
		`{"localPort":7778}`,
		`{"localPort":"7777"}`,
		`{"hots":"typo"}`,
		`{"host":"a"} {"host":"b"}`,
		`not json`,
		strings.Repeat(" ", maxConfig+1),
	}
	for _, in := range bad {
		if _, err := ParseConfig(strings.NewReader(in)); err == nil {
			t.Errorf("accepted %q", in)
		}
	}
}

func TestBrowserCandidates(t *testing.T) {
	env := map[string]string{
		"ProgramFiles(x86)": `C:\Program Files (x86)`,
		"ProgramFiles":      `C:\Program Files`,
		"LOCALAPPDATA":      `C:\Users\jay\AppData\Local`,
	}
	app := map[string]string{
		"msedge.exe": `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, // duplicate: dropped
		"chrome.exe": `D:\Apps\Chrome\chrome.exe`,
	}
	got := BrowserCandidates(func(k string) string { return env[k] }, func(e string) string { return app[e] })
	want := []string{
		`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
		`C:\Program Files\Microsoft\Edge\Application\msedge.exe`,
		`C:\Program Files\Google\Chrome\Application\chrome.exe`,
		`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
		`C:\Users\jay\AppData\Local\Google\Chrome\Application\chrome.exe`,
		`D:\Apps\Chrome\chrome.exe`,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got\n%s", strings.Join(got, "\n"))
	}
	if n := len(BrowserCandidates(func(string) string { return "" }, func(string) string { return "" })); n != 0 {
		t.Fatalf("empty env gave %d candidates", n)
	}
	args := BrowserArgs("http://127.0.0.1:7777", `C:\Users\jay\AppData\Local\CommandCenter\Browser`)
	wantArgs := []string{"--app=http://127.0.0.1:7777",
		`--user-data-dir=C:\Users\jay\AppData\Local\CommandCenter\Browser`, "--no-first-run", "--no-default-browser-check"}
	if !reflect.DeepEqual(args, wantArgs) {
		t.Fatalf("args %q", args)
	}
}

func TestFindSSH(t *testing.T) {
	env := func(k string) string { return map[string]string{"SystemRoot": `C:\WINDOWS`}[k] }
	builtin := `C:\WINDOWS\System32\OpenSSH\ssh.exe`
	p, ok := FindSSH(env, func(s string) bool { return s == builtin }, func(string) (string, error) { return "", errors.New("no") })
	if !ok || p != builtin {
		t.Fatalf("got %q %v", p, ok)
	}
	p, ok = FindSSH(env, func(string) bool { return false }, func(string) (string, error) { return `C:\Git\usr\bin\ssh.exe`, nil })
	if !ok || p != `C:\Git\usr\bin\ssh.exe` {
		t.Fatalf("got %q %v", p, ok)
	}
	if _, ok = FindSSH(env, func(string) bool { return false }, func(string) (string, error) { return "", errors.New("no") }); ok {
		t.Fatal("found ssh that does not exist")
	}
	if AppDir(func(string) string { return `C:\Users\jay\AppData\Local\` }) != `C:\Users\jay\AppData\Local\CommandCenter` {
		t.Fatal("AppDir")
	}
}

const ccdHealth = `{"ok":true,"herdr":{"ok":true,"connected":true},"gh":{"ok":true,"projects":{}},
"git":{"asOf":1,"error":null},"host":{"asOf":1,"error":null},"tasks":{"enabled":true,"schemaVersion":3},
"seq":42,"uptimeS":12.5,"version":"0.4.0"}`

func TestIsCCDHealth(t *testing.T) {
	if !IsCCDHealth(200, []byte(ccdHealth)) {
		t.Fatal("real ccd health not recognised")
	}
	// ccd degraded (ok:false) is still ccd: reuse it rather than fight it for the port
	if !IsCCDHealth(200, []byte(`{"ok":false,"herdr":{"ok":false},"seq":0,"uptimeS":0.1,"version":"0.4.0"}`)) {
		t.Fatal("degraded ccd not recognised")
	}
	foreign := map[int]string{
		200: `{"status":"ok"}`,
		201: ccdHealth,
		403: `bad Host header`,
		404: `<html>not found</html>`,
	}
	for code, body := range foreign {
		if IsCCDHealth(code, []byte(body)) {
			t.Errorf("%d %q recognised as ccd", code, body)
		}
	}
	for _, body := range []string{
		`[]`, `null`, `{"herdr":null,"seq":1,"uptimeS":1,"version":"x"}`,
		`{"herdr":{},"seq":"1","uptimeS":1,"version":"x"}`,
		`{"herdr":{},"seq":1,"uptimeS":1,"version":""}`,
		`{"herdr":{},"seq":1,"version":"x"}`,
	} {
		if IsCCDHealth(200, []byte(body)) {
			t.Errorf("%q recognised as ccd", body)
		}
	}
}

func portOf(t *testing.T, addr string) int {
	_, p, _ := net.SplitHostPort(addr)
	n, err := strconv.Atoi(p)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func TestClassifyPort(t *testing.T) {
	ccd := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/health" {
			http.NotFound(w, r)
			return
		}
		w.Write([]byte(ccdHealth))
	}))
	defer ccd.Close()
	if got := ClassifyPort(portOf(t, ccd.Listener.Addr().String())); got != PortCCD {
		t.Errorf("ccd: %v", got)
	}

	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"hello":"world"}`))
	}))
	defer other.Close()
	if got := ClassifyPort(portOf(t, other.Listener.Addr().String())); got != PortForeign {
		t.Errorf("foreign http: %v", got)
	}

	raw, _ := net.Listen("tcp", "127.0.0.1:0") // accepts, never speaks HTTP
	go func() {
		for {
			c, err := raw.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	if got := ClassifyPort(portOf(t, raw.Addr().String())); got != PortForeign {
		t.Errorf("raw tcp: %v", got)
	}
	free := portOf(t, raw.Addr().String())
	raw.Close()
	time.Sleep(50 * time.Millisecond)
	if got := ClassifyPort(free); got != PortFree {
		t.Errorf("free: %v", got)
	}
}

func TestBackoff(t *testing.T) {
	want := []time.Duration{2, 5, 10, 20, 30, 30, 30, 30}
	for i, w := range want {
		if got := Backoff(i + 1); got != w*time.Second {
			t.Errorf("attempt %d: %v", i+1, got)
		}
	}
	if Backoff(0) != 2*time.Second || Backoff(1000) != 30*time.Second {
		t.Error("bounds")
	}
	var total time.Duration
	for i := 1; i <= maxReconnects; i++ {
		total += Backoff(i)
	}
	if total > 5*time.Minute {
		t.Errorf("gives up only after %v", total)
	}
}

func TestLastLine(t *testing.T) {
	if got := LastLine("a\r\nssh: connect to host x port 22: Connection refused\r\n\r\n", 200); got != "ssh: connect to host x port 22: Connection refused" {
		t.Errorf("%q", got)
	}
	if got := LastLine(strings.Repeat("x", 300), 10); got != "xxxxxxxxxx..." {
		t.Errorf("%q", got)
	}
	if got := LastLine("bad\x1b[31m\x00", 50); got != "bad[31m" {
		t.Errorf("%q", got)
	}
	tb := newTail(8)
	tb.Write([]byte("0123456789abcdef"))
	if got := tb.LastLine(); got != "89abcdef" {
		t.Errorf("tail %q", got)
	}
}

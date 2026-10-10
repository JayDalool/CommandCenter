package main

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestParseGates(t *testing.T) {
	cases := []struct {
		name   string
		status int
		body   string
		want   GateReading
		ok     bool
	}{
		{"normal", 200, `{"ok":true,"gates":{"open":3,"last":120},"seq":1}`, GateReading{3, 120}, true},
		{"none open", 200, `{"gates":{"open":0,"last":0}}`, GateReading{0, 0}, true},
		{"older ccd", 200, `{"ok":true,"seq":1}`, GateReading{}, false},
		{"not 200", 503, `{"gates":{"open":1,"last":2}}`, GateReading{}, false},
		{"missing last", 200, `{"gates":{"open":1}}`, GateReading{}, false},
		{"missing open", 200, `{"gates":{"last":1}}`, GateReading{}, false},
		{"strings", 200, `{"gates":{"open":"1","last":"2"}}`, GateReading{}, false},
		{"fractions", 200, `{"gates":{"open":1.5,"last":2}}`, GateReading{}, false},
		{"negative", 200, `{"gates":{"open":-1,"last":2}}`, GateReading{}, false},
		{"null", 200, `{"gates":null}`, GateReading{}, false},
		{"not json", 200, `<html>`, GateReading{}, false},
	}
	for _, c := range cases {
		got, ok := ParseGates(c.status, []byte(c.body))
		if ok != c.ok || got != c.want {
			t.Errorf("%s: got %+v %v, want %+v %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestGateWatchObserve(t *testing.T) {
	var w gateWatch
	steps := []struct {
		r      GateReading
		notify bool
		why    string
	}{
		{GateReading{2, 10}, false, "first reading is a silent baseline, even with gates open"},
		{GateReading{2, 10}, false, "nothing new"},
		{GateReading{3, 11}, true, "a new gate while others are open"},
		{GateReading{3, 11}, false, "the same one is not announced twice"},
		{GateReading{2, 11}, false, "a gate closed"},
		{GateReading{0, 12}, false, "new event but nothing open (blocked, then cleared)"},
		{GateReading{1, 12}, false, "a gate opened without a newer marker is not a new event"},
		{GateReading{1, 15}, true, "marker jumped"},
		{GateReading{1, 3}, false, "marker went backwards (restored database): new baseline"},
		{GateReading{1, 3}, false, "still the baseline"},
		{GateReading{1, 4}, true, "grows from the new baseline"},
	}
	for i, s := range steps {
		if got := w.Observe(s.r); got != s.notify {
			t.Fatalf("step %d (%s): notify %v, want %v", i, s.why, got, s.notify)
		}
	}
}

func TestGateNoticeText(t *testing.T) {
	if got := GateNoticeText(3); got != "A new item needs you (3 open)" {
		t.Fatalf("%q", got)
	}
}

// ReadGates against a real HTTP server: a good body, and bodies that must stay silent.
func TestReadGates(t *testing.T) {
	var mu sync.Mutex
	status, body := 200, `{"gates":{"open":2,"last":7}}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if r.URL.Path != "/api/health" {
			t.Errorf("path %s", r.URL.Path)
		}
		if len(r.Header) > 3 { // Host, User-Agent, Accept-Encoding: nothing that could be a credential
			t.Errorf("unexpected request headers %v", r.Header)
		}
		w.WriteHeader(status)
		w.Write([]byte(body))
	}))
	defer srv.Close()
	port := portOf(t, srv.Listener.Addr().String())
	g, err := ReadGates(port)
	if err != nil || g != (GateReading{2, 7}) {
		t.Fatalf("%+v %v", g, err)
	}
	mu.Lock()
	body = `{"ok":true}`
	mu.Unlock()
	if _, err := ReadGates(port); !errors.Is(err, errNoGates) {
		t.Fatalf("older ccd: %v", err)
	}
	srv.Close()
	if _, err := ReadGates(port); err == nil {
		t.Fatal("no error with the server gone")
	}
}

// scripted feeds watchGates a script: each entry is a reading or an error;
// after the script ends it repeats the last entry.
type scripted struct {
	mu    sync.Mutex
	steps []gateStep
	n     int
}

type gateStep struct {
	r   GateReading
	err error
}

func (s *scripted) read(int) (GateReading, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	i := s.n
	if i >= len(s.steps) {
		i = len(s.steps) - 1
	} else {
		s.n++
	}
	return s.steps[i].r, s.steps[i].err
}

func (s *scripted) done() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.n >= len(s.steps)
}

func TestWatchGatesNotifiesOncePerNewGate(t *testing.T) {
	s := &scripted{steps: []gateStep{
		{GateReading{1, 5}, nil},            // baseline
		{GateReading{}, errors.New("down")}, // tunnel blip: silent
		{GateReading{1, 5}, nil},
		{GateReading{2, 6}, nil}, // notice 1
		{GateReading{2, 6}, nil},
		{GateReading{3, 9}, nil}, // notice 2
		{GateReading{3, 9}, nil},
	}}
	a := &app{gateRead: s.read, gateEvery: time.Millisecond}
	stop := make(chan struct{})
	notices := make(chan string, 10)
	finished := make(chan struct{})
	go func() { a.watchGates(7777, stop, notices); close(finished) }()
	deadline := time.Now().Add(5 * time.Second)
	for !s.done() {
		if time.Now().After(deadline) {
			t.Fatal("script not consumed")
		}
		time.Sleep(time.Millisecond)
	}
	time.Sleep(10 * time.Millisecond)
	close(stop)
	select {
	case <-finished:
	case <-time.After(5 * time.Second):
		t.Fatal("watchGates did not stop")
	}
	close(notices)
	var got []string
	for n := range notices {
		got = append(got, n)
	}
	want := []string{"A new item needs you (2 open)", "A new item needs you (3 open)"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("notices %q, want %q", got, want)
	}
}

// A full channel drops the notice instead of blocking the poll loop.
func TestWatchGatesNeverBlocks(t *testing.T) {
	s := &scripted{steps: []gateStep{{GateReading{1, 1}, nil}, {GateReading{1, 2}, nil}, {GateReading{1, 3}, nil}, {GateReading{1, 4}, nil}}}
	a := &app{gateRead: s.read, gateEvery: time.Millisecond}
	stop := make(chan struct{})
	finished := make(chan struct{})
	go func() { a.watchGates(7777, stop, make(chan string)); close(finished) }() // nobody reads
	deadline := time.Now().Add(5 * time.Second)
	for !s.done() {
		if time.Now().After(deadline) {
			t.Fatal("poll loop blocked on a full channel")
		}
		time.Sleep(time.Millisecond)
	}
	close(stop)
	<-finished
}

// In window mode the launcher shows the tray, passes it the notices, and
// Quit stops the tunnel while the window stays open.
func TestRunWindowModeTrayGetsNoticesAndQuitStopsTunnel(t *testing.T) {
	f := newFake()
	s := &scripted{steps: []gateStep{{GateReading{0, 1}, nil}, {GateReading{1, 2}, nil}}}
	got := make(chan string, 1)
	quit := make(chan struct{})
	f.tray = func(m TrayMenu, stop <-chan struct{}) error {
		if m.Notices == nil {
			t.Error("no Notices channel on the tray")
			return nil
		}
		select {
		case n := <-m.Notices:
			got <- n
		case <-time.After(5 * time.Second):
			t.Error("no notice reached the tray")
		}
		<-quit // Quit
		return nil
	}
	a := testApp(f, PortFree, always(true))
	a.handoff = time.Hour // the browser stays "open"; only the tray ends the run
	a.gateRead, a.gateEvery = s.read, time.Millisecond
	done := runAsync(a)
	select {
	case n := <-got:
		if n != "A new item needs you (1 open)" {
			t.Fatalf("notice %q", n)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no notice")
	}
	f.mu.Lock()
	windows := len(f.browser)
	f.mu.Unlock()
	if windows != 1 {
		t.Fatalf("browser windows %d", windows)
	}
	select {
	case <-done:
		t.Fatal("exited before Quit")
	case <-time.After(20 * time.Millisecond):
	}
	close(quit)
	if code := waitExit(t, done); code != 0 {
		t.Fatalf("exit %d", code)
	}
	f.assertAllSSHKilled(t)
	if len(f.alerts) != 0 {
		t.Fatalf("alerts %q", f.alerts)
	}
}

// Closing the window still ends the run in window mode, and takes the tray down first.
func TestRunWindowCloseStopsTrayToo(t *testing.T) {
	f := newFake()
	f.browserExit = true // the window closes at once; handoff = 0 counts that as "closed"
	trayStopped := make(chan struct{})
	f.tray = func(m TrayMenu, stop <-chan struct{}) error {
		<-stop
		close(trayStopped)
		return nil
	}
	a := testApp(f, PortFree, always(true))
	a.gateRead = func(int) (GateReading, error) { return GateReading{}, errors.New("down") } // errors are silent
	done := runAsync(a)
	if code := waitExit(t, done); code != 0 {
		t.Fatalf("exit %d", code)
	}
	select {
	case <-trayStopped:
	case <-time.After(5 * time.Second):
		t.Fatal("tray was not stopped")
	}
	if len(f.alerts) != 0 {
		t.Fatalf("alerts %q", f.alerts)
	}
	f.assertAllSSHKilled(t)
}

// Reuse and second launch hold no tunnel: they must not poll, and no tray appears.
func TestRunReuseAndSecondLaunchNeverPoll(t *testing.T) {
	for _, first := range []bool{true, false} {
		f := newFake()
		f.first = first
		state := PortCCD
		if !first {
			state = PortFree
		}
		a := testApp(f, state, always(true))
		reads := 0
		a.gateRead = func(int) (GateReading, error) { reads++; return GateReading{1, 1}, nil }
		a.gateEvery = time.Millisecond
		if code := a.run(); code != 0 {
			t.Fatalf("first=%v exit %d", first, code)
		}
		time.Sleep(10 * time.Millisecond)
		if reads != 0 || f.trays != 0 {
			t.Fatalf("first=%v: polled %d times, trays %d", first, reads, f.trays)
		}
	}
}

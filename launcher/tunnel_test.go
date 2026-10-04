package main

import (
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeProc struct {
	once sync.Once
	exit chan struct{}
	kill int
	mu   sync.Mutex
}

func newFakeProc() *fakeProc    { return &fakeProc{exit: make(chan struct{})} }
func (f *fakeProc) Wait() error { <-f.exit; return errors.New("exit status 255") }
func (f *fakeProc) end()        { f.once.Do(func() { close(f.exit) }) }
func (f *fakeProc) Kill() error {
	f.mu.Lock()
	f.kill++
	f.mu.Unlock()
	f.end()
	return nil
}

const openTimeout = 999 * time.Second

// instant timers so the backoff schedule is observed, not slept.
func recordAfter(waits *[]time.Duration, mu *sync.Mutex) func(time.Duration) <-chan time.Time {
	return func(d time.Duration) <-chan time.Time {
		if d == openTimeout { // the open timeout never fires in these tests
			return make(chan time.Time)
		}
		if d >= time.Second {
			mu.Lock()
			*waits = append(*waits, d)
			mu.Unlock()
		}
		c := make(chan time.Time, 1)
		c <- time.Now()
		return c
	}
}

func TestTunnelOpenSSHExits(t *testing.T) {
	tn := newTunnel(func(stderr *tailBuffer) (Proc, error) {
		p := newFakeProc()
		stderr.Write([]byte("Warning: x\r\njay-server: Permission denied (publickey).\r\n"))
		p.end()
		return p, nil
	}, func() bool { return false }, &logger{})
	tn.poll = time.Millisecond
	err := tn.Open()
	var se *sshExitError
	if !errors.As(err, &se) || se.line != "jay-server: Permission denied (publickey)." {
		t.Fatalf("got %v", err)
	}
	if !strings.Contains(openFailure(DefaultConfig(), err), "Permission denied") {
		t.Fatal("message lost ssh's reason")
	}
}

func TestTunnelOpenNoAnswerKillsSSH(t *testing.T) {
	p := newFakeProc()
	tn := newTunnel(func(*tailBuffer) (Proc, error) { return p, nil }, func() bool { return false }, &logger{})
	tn.poll = time.Millisecond
	tn.timeout = 30 * time.Millisecond
	if err := tn.Open(); !errors.Is(err, errNoAnswer) {
		t.Fatalf("got %v", err)
	}
	if p.kill != 1 {
		t.Fatal("ssh left running after timeout")
	}
}

func TestTunnelReconnectsWithBackoffThenGivesUp(t *testing.T) {
	var mu sync.Mutex
	var waits []time.Duration
	var procs []*fakeProc
	starts := 0
	tn := newTunnel(func(stderr *tailBuffer) (Proc, error) {
		mu.Lock()
		defer mu.Unlock()
		starts++
		p := newFakeProc()
		procs = append(procs, p)
		if starts > 1 { // every reconnect fails at once
			stderr.Write([]byte("ssh: connect to host jay-server port 22: Network is unreachable\n"))
			p.end()
		}
		return p, nil
	}, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return starts == 1
	}, &logger{})
	tn.after = recordAfter(&waits, &mu)
	tn.timeout = openTimeout
	tn.poll = time.Millisecond
	if err := tn.Open(); err != nil {
		t.Fatal(err)
	}
	stop := make(chan struct{})
	res := make(chan error, 1)
	go func() { res <- tn.Supervise(stop) }()
	procs[0].end() // tunnel drops while the browser is open
	select {
	case err := <-res:
		if err == nil || !strings.Contains(err.Error(), "Network is unreachable") {
			t.Fatalf("got %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("supervisor never gave up")
	}
	mu.Lock()
	defer mu.Unlock()
	want := []time.Duration{2, 5, 10, 20, 30, 30, 30, 30}
	if len(waits) != len(want) {
		t.Fatalf("waits %v", waits)
	}
	for i := range want {
		if waits[i] != want[i]*time.Second {
			t.Fatalf("waits %v", waits)
		}
	}
	if starts != 1+maxReconnects {
		t.Fatalf("starts %d", starts)
	}
}

func TestTunnelReconnectSucceedsAndStopKillsOnlyOurs(t *testing.T) {
	var mu sync.Mutex
	var waits []time.Duration
	var procs []*fakeProc
	tn := newTunnel(func(*tailBuffer) (Proc, error) {
		mu.Lock()
		defer mu.Unlock()
		p := newFakeProc()
		procs = append(procs, p)
		return p, nil
	}, func() bool { return true }, &logger{})
	tn.after = recordAfter(&waits, &mu)
	tn.timeout = openTimeout
	if err := tn.Open(); err != nil {
		t.Fatal(err)
	}
	stop := make(chan struct{})
	res := make(chan error, 1)
	go func() { res <- tn.Supervise(stop) }()
	procs[0].end()
	deadline := time.Now().Add(5 * time.Second)
	for {
		mu.Lock()
		n := len(procs)
		mu.Unlock()
		if n == 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("no reconnect")
		}
		time.Sleep(time.Millisecond)
	}
	close(stop)
	if err := <-res; err != nil {
		t.Fatal(err)
	}
	tn.Close()
	if procs[1].kill != 1 {
		t.Fatal("current ssh not killed on close")
	}
	if waits[0] != 2*time.Second {
		t.Fatalf("first wait %v", waits)
	}
}

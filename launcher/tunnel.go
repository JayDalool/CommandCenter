package main

import (
	"errors"
	"fmt"
	"sync"
	"time"
)

// Proc is a started child process (ssh or a browser).
type Proc interface {
	Wait() error
	Kill() error
}

// sshExitError: ssh ended before ccd answered through it.
type sshExitError struct{ line string }

func (e *sshExitError) Error() string {
	if e.line == "" {
		return "ssh exited"
	}
	return "ssh exited: " + e.line
}

// errNoAnswer: ssh is up but ccd never answered through the tunnel.
var errNoAnswer = errors.New("tunnel is up but Command Center did not answer")

// errClosed: Close ran; the tunnel never starts another ssh.
var errClosed = errors.New("tunnel closed")

// tunnel owns exactly one ssh process at a time: the one it started.
type tunnel struct {
	start   func(stderr *tailBuffer) (Proc, error)
	probe   func() bool
	after   func(time.Duration) <-chan time.Time
	poll    time.Duration
	timeout time.Duration
	log     *logger
	stderr  *tailBuffer

	mu     sync.Mutex
	cur    Proc
	done   chan error
	closed bool // set by Close: no ssh may start after it
	manual bool // set by Reconnect: restart now, without backoff
	kick   chan struct{}
}

func newTunnel(start func(*tailBuffer) (Proc, error), probe func() bool, log *logger) *tunnel {
	return &tunnel{
		start: start, probe: probe, after: time.After,
		poll: 300 * time.Millisecond, timeout: 20 * time.Second,
		log: log, stderr: newTail(4 << 10), kick: make(chan struct{}, 1),
	}
}

// Open starts ssh and waits until ccd answers through it. On failure the ssh
// it started is killed and the error says why.
func (t *tunnel) Open() error {
	if t.isClosed() {
		return errClosed
	}
	t.stderr.Reset()
	p, err := t.start(t.stderr)
	if err != nil {
		return fmt.Errorf("could not start ssh: %w", err)
	}
	done := make(chan error, 1)
	go func() { done <- p.Wait() }()
	t.mu.Lock()
	if t.closed { // Close ran while ssh was starting
		t.mu.Unlock()
		_ = p.Kill()
		return errClosed
	}
	t.cur, t.done = p, done
	t.mu.Unlock()

	deadline := t.after(t.timeout)
	for {
		if t.probe() {
			t.log.Printf("tunnel up")
			return nil
		}
		select {
		case <-done:
			done <- nil // keep the exit visible to Supervise/Close
			return &sshExitError{line: t.stderr.LastLine()}
		case <-deadline:
			_ = p.Kill() // this ssh only; the tunnel stays usable for a retry
			return errNoAnswer
		case <-t.after(t.poll):
		}
	}
}

// Supervise restarts ssh with backoff while the browser is open. It returns
// nil when stop closes (or Close ran), or an error after maxReconnects
// consecutive failures. After Reconnect the first attempt is immediate.
func (t *tunnel) Supervise(stop <-chan struct{}) error {
	fails := 0
	for {
		upAt := time.Now()
		t.mu.Lock()
		done := t.done
		t.mu.Unlock()
		select {
		case <-stop:
			return nil
		case <-done:
		}
		t.mu.Lock()
		manual := t.manual
		t.manual = false
		t.mu.Unlock()
		select { // the kill above already did what a kick would
		case <-t.kick:
		default:
		}
		if manual {
			t.log.Printf("reconnect requested")
			fails = 0
		} else {
			t.log.Printf("ssh exited: %s", t.stderr.LastLine())
			if time.Since(upAt) >= stableAfter {
				fails = 0
			}
		}
		wait := !manual
		for {
			if wait {
				fails++
				if fails > maxReconnects {
					return fmt.Errorf("lost the connection and could not reconnect after %d tries. Last ssh message: %s",
						maxReconnects, orNone(t.stderr.LastLine()))
				}
				select {
				case <-stop:
					return nil
				case <-t.kick: // Reconnect during the wait: try now
					t.mu.Lock()
					t.manual = false
					t.mu.Unlock()
				case <-t.after(Backoff(fails)):
				}
			}
			wait = true
			select {
			case <-stop:
				return nil
			default:
			}
			err := t.Open()
			if err == nil {
				break
			}
			if errors.Is(err, errClosed) {
				return nil
			}
			t.log.Printf("reconnect %d failed: %v", fails, err)
		}
	}
}

// Reconnect kills our current ssh so Supervise starts a fresh one at once.
func (t *tunnel) Reconnect() {
	t.mu.Lock()
	if t.closed || t.cur == nil {
		t.mu.Unlock()
		return
	}
	t.manual = true
	select { // queued before the kill, so Supervise drains it when ssh exits
	case t.kick <- struct{}{}:
	default:
	}
	p := t.cur
	t.mu.Unlock()
	_ = p.Kill()
}

func (t *tunnel) isClosed() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.closed
}

// Close kills the ssh this tunnel started (and only that one) and stops any
// later Open from starting another.
func (t *tunnel) Close() {
	t.mu.Lock()
	t.closed = true
	p := t.cur
	t.mu.Unlock()
	if p != nil {
		_ = p.Kill()
	}
}

func orNone(s string) string {
	if s == "" {
		return "(none)"
	}
	return s
}

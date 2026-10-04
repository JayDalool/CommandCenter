package main

import (
	"strings"
	"sync"
)

// tailBuffer keeps only the last few KB of ssh's stderr.
type tailBuffer struct {
	mu  sync.Mutex
	buf []byte
	max int
}

func newTail(max int) *tailBuffer { return &tailBuffer{max: max} }

func (t *tailBuffer) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.buf = append(t.buf, p...)
	if len(t.buf) > t.max {
		t.buf = append([]byte(nil), t.buf[len(t.buf)-t.max:]...)
	}
	return len(p), nil
}

func (t *tailBuffer) Reset() {
	t.mu.Lock()
	t.buf = nil
	t.mu.Unlock()
}

func (t *tailBuffer) LastLine() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return LastLine(string(t.buf), 200)
}

// LastLine returns the last non-empty line, printable ASCII only, capped at max.
func LastLine(s string, max int) string {
	lines := strings.Split(strings.ReplaceAll(s, "\r", "\n"), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		l := strings.TrimSpace(strings.Map(func(r rune) rune {
			if r < 0x20 || r > 0x7e {
				return -1
			}
			return r
		}, lines[i]))
		if l != "" {
			if len(l) > max {
				l = l[:max] + "..."
			}
			return l
		}
	}
	return ""
}

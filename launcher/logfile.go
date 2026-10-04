package main

import (
	"fmt"
	"os"
	"sync"
	"time"
)

// A tiny event log (start, reuse, ssh exit, browser path). It never records
// tokens, keys or the environment; ssh stderr appears only as its capped last line.
const maxLog = 256 << 10

type logger struct {
	mu sync.Mutex
	f  *os.File
}

func openLog(path string) *logger {
	if path == "" {
		return &logger{}
	}
	if st, err := os.Stat(path); err == nil && st.Size() > maxLog {
		_ = os.Remove(path + ".1")
		_ = os.Rename(path, path+".1")
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return &logger{}
	}
	return &logger{f: f}
}

func (l *logger) Printf(format string, a ...any) {
	if l == nil || l.f == nil {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Fprintf(l.f, "%s %s\n", time.Now().UTC().Format(time.RFC3339), fmt.Sprintf(format, a...))
}

func (l *logger) Close() {
	if l != nil && l.f != nil {
		l.f.Close()
	}
}

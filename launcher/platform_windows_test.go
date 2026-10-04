//go:build windows

package main

import (
	"runtime"
	"testing"
	"time"
	"unsafe"
)

func TestJobStructLayout(t *testing.T) {
	if runtime.GOARCH == "amd64" && unsafe.Sizeof(jobExtendedLimit{}) != 144 {
		t.Fatalf("JOBOBJECT_EXTENDED_LIMIT_INFORMATION size %d, want 144", unsafe.Sizeof(jobExtendedLimit{}))
	}
}

// The job must exist and kill what we put in it when it closes.
func TestJobKillsChildOnClose(t *testing.T) {
	p := newPlatform()
	if p.job == 0 {
		t.Fatal("job object not created")
	}
	tb := newTail(1024)
	proc, err := p.StartSSH(`C:\Windows\System32\PING.EXE`, []string{"-n", "60", "127.0.0.1"}, tb)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() { proc.Wait(); close(done) }()
	p.Shutdown()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		proc.Kill()
		t.Fatal("child survived job close")
	}
}

func TestAppPathDoesNotPanic(t *testing.T) {
	_ = newPlatform().AppPath("msedge.exe")
}

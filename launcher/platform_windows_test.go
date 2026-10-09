//go:build windows

package main

import (
	"fmt"
	"os"
	"runtime"
	"strings"
	"syscall"
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

func TestTrayStructLayout(t *testing.T) {
	if runtime.GOARCH != "amd64" {
		t.Skip("sizes checked for amd64")
	}
	if n := unsafe.Sizeof(notifyIconData{}); n != 976 {
		t.Fatalf("NOTIFYICONDATAW size %d, want 976", n)
	}
	if n := unsafe.Sizeof(wndClassEx{}); n != 80 {
		t.Fatalf("WNDCLASSEXW size %d, want 80", n)
	}
	if n := unsafe.Sizeof(winMsg{}); n != 48 {
		t.Fatalf("MSG size %d, want 48", n)
	}
}

func TestFirstInstanceMutex(t *testing.T) {
	name := fmt.Sprintf(`Local\CommandCenterLauncherTest-%d`, os.Getpid())
	a, b := newPlatform(), newPlatform()
	defer a.Shutdown()
	defer b.Shutdown()
	if !a.FirstInstance(name) {
		t.Fatal("first launcher not first")
	}
	if b.FirstInstance(name) {
		t.Fatal("second launcher also first")
	}
}

// The tray must come up (or fail cleanly where there is no shell, as on
// some CI sessions) and go away when stop closes, twice in a row.
func TestTrayStopsOnRequest(t *testing.T) {
	p := newPlatform()
	defer p.Shutdown()
	for i := 0; i < 2; i++ {
		stop := make(chan struct{})
		res := make(chan error, 1)
		go func() { res <- p.Tray(TrayMenu{Tip: "test", Open: func() {}, Reconnect: func() {}}, stop) }()
		time.Sleep(300 * time.Millisecond)
		close(stop)
		select {
		case err := <-res:
			t.Logf("tray run %d: %v", i, err)
		case <-time.After(10 * time.Second):
			t.Fatal("tray did not stop")
		}
	}
}

func TestFillBalloon(t *testing.T) {
	var nid notifyIconData
	nid.UFlags = nifMessage | nifIcon | nifTip
	fillBalloon(&nid, GateNoticeText(3))
	if got := syscall.UTF16ToString(nid.SzInfo[:]); got != "A new item needs you (3 open)" {
		t.Fatalf("info %q", got)
	}
	if got := syscall.UTF16ToString(nid.SzInfoTitle[:]); got != title {
		t.Fatalf("title %q", got)
	}
	if nid.UFlags != nifMessage|nifIcon|nifTip|nifInfo || nid.DwInfoFlags != niifInfo {
		t.Fatalf("flags %#x info flags %#x", nid.UFlags, nid.DwInfoFlags)
	}
	// longer than the 256-slot buffer: cut, still zero-terminated
	fillBalloon(&nid, strings.Repeat("x", 400))
	if n := len(syscall.UTF16ToString(nid.SzInfo[:])); n != 255 {
		t.Fatalf("long text kept %d characters, want 255", n)
	}
}

// A notice sent to a running tray must not hang or crash it, and the tray must
// still stop on request. (Whether the balloon is drawn is for a person to see;
// CI sessions may have no shell.)
func TestTrayAcceptsNotices(t *testing.T) {
	p := newPlatform()
	defer p.Shutdown()
	stop := make(chan struct{})
	notices := make(chan string, 2)
	res := make(chan error, 1)
	go func() {
		res <- p.Tray(TrayMenu{Tip: "test", Open: func() {}, Reconnect: func() {}, Notices: notices}, stop)
	}()
	time.Sleep(300 * time.Millisecond)
	notices <- GateNoticeText(1)
	notices <- GateNoticeText(2)
	time.Sleep(200 * time.Millisecond)
	close(stop)
	select {
	case err := <-res:
		t.Logf("tray run: %v", err)
	case <-time.After(10 * time.Second):
		t.Fatal("tray did not stop")
	}
}

// escapeArg must match the real syscall.EscapeArg that os/exec uses.
func TestEscapeArgMatchesSyscall(t *testing.T) {
	for _, s := range []string{"", "a", "a b", `a"b`, `C:\a b\`, `x\\"y`, "tab\tx", "Claude — SamVision",
		`$Host.UI.RawUI.WindowTitle='x'; & 'C:\P F\J''s\ssh.exe' '-t'`} {
		if got, want := escapeArg(s), syscall.EscapeArg(s); got != want {
			t.Errorf("%q: got %s want %s", s, got, want)
		}
	}
}

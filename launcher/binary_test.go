package main

import (
	"bytes"
	"encoding/binary"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
)

// Forbidden in the shipped binary: anything that would mean a credential, or
// the path to one, got compiled in. Kept as fragments so this file's own
// constants cannot be mistaken for the real thing by other scanners.
var forbidden = []string{
	"ccd" + ".token",
	"developer" + ".token",
	"BEGIN " + "OPENSSH",
	"BEGIN RSA " + "PRIVATE",
	"github" + "_pat_",
	"ghp" + "_",
	"X-CCD-" + "Token",
	"id_" + "ed25519",
	"id_" + "rsa",
}

// ScanForbidden returns the forbidden strings present in data.
func ScanForbidden(data []byte) []string {
	var hits []string
	for _, f := range forbidden {
		if bytes.Contains(data, []byte(f)) {
			hits = append(hits, f)
		}
	}
	return hits
}

func TestBinaryHasNoSecrets(t *testing.T) {
	if testing.Short() {
		t.Skip("builds the Windows binary")
	}
	exe := filepath.Join(t.TempDir(), "CommandCenter.exe")
	goBin := filepath.Join(runtime.GOROOT(), "bin", "go")
	if _, err := os.Stat(goBin); err != nil {
		goBin = "go"
	}
	cmd := exec.Command(goBin, "build", "-trimpath", "-ldflags", "-H windowsgui -s -w", "-o", exe, ".")
	cmd.Env = append(os.Environ(), "GOOS=windows", "GOARCH=amd64", "CGO_ENABLED=0")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	data, err := os.ReadFile(exe)
	if err != nil {
		t.Fatal(err)
	}
	if hits := ScanForbidden(data); len(hits) > 0 {
		t.Fatalf("binary contains %q", hits)
	}
	if !bytes.HasPrefix(data, []byte("MZ")) {
		t.Fatal("not a PE file")
	}
	// Double-click must not flash a console: IMAGE_SUBSYSTEM_WINDOWS_GUI (2).
	pe := int(binary.LittleEndian.Uint32(data[0x3c:]))
	if string(data[pe:pe+4]) != "PE\x00\x00" {
		t.Fatal("no PE signature")
	}
	if sub := binary.LittleEndian.Uint16(data[pe+24+68:]); sub != 2 {
		t.Fatalf("subsystem %d, want 2 (Windows GUI)", sub)
	}
	// the scanner itself must work
	if len(ScanForbidden([]byte("x "+forbidden[0]+" y"))) != 1 {
		t.Fatal("scanner broken")
	}
}

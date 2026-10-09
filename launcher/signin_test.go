package main

import (
	"errors"
	"strings"
	"testing"
)

func TestSigninArgsRunOnlyTheFixedHelperAfterDashDash(t *testing.T) {
	cfg := DefaultConfig()
	got := strings.Join(SigninArgs(cfg), " ")
	want := "-T -o BatchMode=yes -o ConnectTimeout=10 -o LogLevel=ERROR -- " + cfg.Host + " " + ccSession
	if got != want {
		t.Fatalf("args = %q, want %q", got, want)
	}
	cfg.RemotePort = 7789
	if a := SigninArgs(cfg); a[len(a)-2] != "--port" || a[len(a)-1] != "7789" {
		t.Fatalf("a preview port is passed to cc-session: %v", a)
	}
}

func TestParseSigninCodeAcceptsOnlyOneCodeLine(t *testing.T) {
	good := strings.Repeat("a", 43)
	if c, err := ParseSigninCode([]byte(good + "\n")); err != nil || c != good {
		t.Fatalf("good code refused: %v", err)
	}
	for _, bad := range []string{"", "short", good + "\n" + good, good + " ; calc", "http://x/" + good, strings.Repeat("a", 200)} {
		if _, err := ParseSigninCode([]byte(bad)); err == nil {
			t.Fatalf("accepted %q", bad)
		}
	}
	if u := SigninURL("http://127.0.0.1:7777", good); u != "http://127.0.0.1:7777/#/?signin="+good {
		t.Fatalf("url = %s", u)
	}
}

func TestSignedURLFallsBackToThePlainURL(t *testing.T) {
	a := &app{log: openLog(""), signin: func(Config) (string, error) { return "", errors.New("no ssh") }}
	if u := a.signedURL(DefaultConfig(), "http://127.0.0.1:7777"); u != "http://127.0.0.1:7777" {
		t.Fatalf("fallback url = %s", u)
	}
	a.signin = func(Config) (string, error) { return strings.Repeat("b", 43), nil }
	if u := a.signedURL(DefaultConfig(), "http://127.0.0.1:7777"); !strings.HasSuffix(u, "#/?signin="+strings.Repeat("b", 43)) {
		t.Fatalf("signed url = %s", u)
	}
}

func TestUnlockLinkTakesNoParameters(t *testing.T) {
	for _, ok := range []string{"commandcenter://unlock", "commandcenter://UNLOCK/", "CommandCenter://unlock"} {
		if a, err := parseAction(ok); err != nil || a.Kind != ActionUnlock {
			t.Fatalf("%s: %v %v", ok, a, err)
		}
	}
	for _, bad := range []string{"commandcenter://unlock?host=evil", "commandcenter://unlock/x", "commandcenter://terminal/unlock"} {
		if _, err := parseAction(bad); err == nil {
			t.Fatalf("accepted %s", bad)
		}
	}
}

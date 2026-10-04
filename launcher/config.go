package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
)

// Config is %LOCALAPPDATA%\CommandCenter\launcher.json. Every field is optional.
// It holds no credentials: ssh authenticates with Jay's own SSH setup.
type Config struct {
	Host       string `json:"host"`
	LocalPort  int    `json:"localPort"`
	RemotePort int    `json:"remotePort"`
}

const (
	defaultHost = "jay-server"
	defaultPort = 7777
	maxConfig   = 16 << 10
)

var hostRE = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)

func DefaultConfig() Config {
	return Config{Host: defaultHost, LocalPort: defaultPort, RemotePort: defaultPort}
}

// ParseConfig reads a launcher.json body over the defaults and validates it.
// Unknown fields are rejected so a typo does not silently fall back to a default.
func ParseConfig(r io.Reader) (Config, error) {
	cfg := DefaultConfig()
	data, err := io.ReadAll(io.LimitReader(r, maxConfig+1))
	if err != nil {
		return cfg, err
	}
	if len(data) > maxConfig {
		return cfg, errors.New("file is too large")
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return cfg, nil
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&cfg); err != nil {
		return cfg, fmt.Errorf("not valid JSON: %v", err)
	}
	if dec.More() {
		return cfg, errors.New("extra data after the JSON object")
	}
	return cfg, cfg.Validate()
}

func (c Config) Validate() error {
	if len(c.Host) == 0 || len(c.Host) > 253 || !hostRE.MatchString(c.Host) || strings.HasPrefix(c.Host, "-") {
		return fmt.Errorf("host %q is not a plain SSH alias or host name (letters, digits, . _ - ; not starting with -)", c.Host)
	}
	for _, p := range []struct {
		name string
		v    int
	}{{"localPort", c.LocalPort}, {"remotePort", c.RemotePort}} {
		if p.v < 1 || p.v > 65535 {
			return fmt.Errorf("%s %d is not a port (1-65535)", p.name, p.v)
		}
	}
	// ccd accepts only Host/Origin 127.0.0.1:<its own port> (DNS-rebinding guard),
	// so a different local port would load a page whose every API call is refused.
	if c.LocalPort != c.RemotePort {
		return fmt.Errorf("localPort (%d) must equal remotePort (%d): ccd only accepts requests addressed to its own port", c.LocalPort, c.RemotePort)
	}
	return nil
}

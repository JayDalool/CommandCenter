package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"
)

type PortState int

const (
	PortFree    PortState = iota // nothing listening: start a tunnel
	PortCCD                      // ccd answers (directly or via an existing tunnel): reuse it
	PortForeign                  // something else owns the port
)

var errNotCCD = errors.New("answered, but not like Command Center")

// IsCCDHealth recognises ccd's GET /api/health body (server/ccd/daemon.py
// health()): an object with "herdr" (object), "seq" (number), "uptimeS"
// (number) and "version" (non-empty string). The endpoint needs no token.
func IsCCDHealth(status int, body []byte) bool {
	if status != http.StatusOK {
		return false
	}
	var m map[string]json.RawMessage
	if json.Unmarshal(body, &m) != nil {
		return false
	}
	var herdr map[string]json.RawMessage
	var seq, up float64
	var ver string
	return m["herdr"] != nil && json.Unmarshal(m["herdr"], &herdr) == nil && herdr != nil &&
		m["seq"] != nil && json.Unmarshal(m["seq"], &seq) == nil &&
		m["uptimeS"] != nil && json.Unmarshal(m["uptimeS"], &up) == nil &&
		m["version"] != nil && json.Unmarshal(m["version"], &ver) == nil && ver != ""
}

var healthClient = &http.Client{
	Timeout:   2 * time.Second,
	Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true},
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

// ProbeCCD reports whether ccd answers on 127.0.0.1:port. It returns errNotCCD
// when something answered HTTP but is not ccd.
func ProbeCCD(port int) (bool, error) {
	resp, err := healthClient.Get(fmt.Sprintf("http://127.0.0.1:%d/api/health", port))
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if err != nil {
		return false, err
	}
	if IsCCDHealth(resp.StatusCode, body) {
		return true, nil
	}
	return false, errNotCCD
}

// ClassifyPort decides between reuse, start-a-tunnel and refuse.
func ClassifyPort(port int) PortState {
	ok, err := ProbeCCD(port)
	if ok {
		return PortCCD
	}
	if errors.Is(err, errNotCCD) {
		return PortForeign
	}
	l, lerr := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if lerr != nil {
		return PortForeign
	}
	l.Close()
	return PortFree
}

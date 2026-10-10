package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

// The launcher holds no token, so the only thing it can learn about Needs Jay
// is the two integers ccd puts in the open GET /api/health:
//
//	"gates": {"open": <open owner gates>, "last": <id of the newest
//	          pipeline.gate_opened / pipeline.blocked event>}
//
// `last` only grows (ticket_events is append-only), so "last went up while
// something is open" means a new item needs Jay. The notice names nothing.

const gatePollEvery = 30 * time.Second

var errNoGates = errors.New("health has no usable gates field")

// GateReading is one /api/health "gates" value.
type GateReading struct {
	Open int64
	Last int64
}

// ParseGates reads "gates" out of a health body. ok is false for any other
// shape (an older ccd without the field, a wrong status, negative numbers):
// the caller then stays silent.
func ParseGates(status int, body []byte) (GateReading, bool) {
	if status != http.StatusOK {
		return GateReading{}, false
	}
	var m struct {
		Gates *struct {
			Open *int64 `json:"open"`
			Last *int64 `json:"last"`
		} `json:"gates"`
	}
	if json.Unmarshal(body, &m) != nil || m.Gates == nil || m.Gates.Open == nil || m.Gates.Last == nil {
		return GateReading{}, false
	}
	if *m.Gates.Open < 0 || *m.Gates.Last < 0 {
		return GateReading{}, false
	}
	return GateReading{Open: *m.Gates.Open, Last: *m.Gates.Last}, true
}

// ReadGates asks ccd on 127.0.0.1:port for its gate counters.
func ReadGates(port int) (GateReading, error) {
	resp, err := healthClient.Get(fmt.Sprintf("http://127.0.0.1:%d/api/health", port))
	if err != nil {
		return GateReading{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if err != nil {
		return GateReading{}, err
	}
	g, ok := ParseGates(resp.StatusCode, body)
	if !ok {
		return GateReading{}, errNoGates
	}
	return g, nil
}

// gateWatch decides when a reading is worth a notice.
type gateWatch struct {
	have bool
	last int64
}

// Observe takes the next reading and reports whether to notify. The first
// reading is a silent baseline. After that a notice needs `last` to have
// grown and at least one gate to be open. If `last` goes backwards (a
// restored database) the new value becomes the baseline, silently.
func (w *gateWatch) Observe(r GateReading) bool {
	if !w.have || r.Last < w.last {
		w.have, w.last = true, r.Last
		return false
	}
	grew := r.Last > w.last
	w.last = r.Last
	return grew && r.Open > 0
}

// GateNoticeText is the balloon text. It carries the count only.
func GateNoticeText(open int64) string {
	return fmt.Sprintf("A new item needs you (%d open)", open)
}

// watchGates polls health every a.gateEvery until stop closes and sends a
// notice for each new gate. Read errors are silent (the tunnel may be
// reconnecting). A full channel drops the notice: the tray shows the latest
// one anyway and the next change will notify again.
func (a *app) watchGates(port int, stop <-chan struct{}, notices chan<- string) {
	var w gateWatch
	tick := time.NewTicker(a.gateEvery)
	defer tick.Stop()
	for {
		if r, err := a.gateRead(port); err == nil && w.Observe(r) {
			select {
			case notices <- GateNoticeText(r.Open):
			default:
			}
		}
		select {
		case <-stop:
			return
		case <-tick.C:
		}
	}
}

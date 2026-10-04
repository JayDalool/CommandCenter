package main

import "time"

// Reconnect policy: 2s, 5s, 10s, 20s, then 30s; give up after maxReconnects
// consecutive failures. A tunnel that stayed up for stableAfter resets the count.
const (
	maxReconnects = 8
	stableAfter   = 60 * time.Second
)

var backoffSteps = []time.Duration{2 * time.Second, 5 * time.Second, 10 * time.Second, 20 * time.Second}

// Backoff returns the wait before reconnect attempt n (1-based).
func Backoff(n int) time.Duration {
	if n < 1 {
		n = 1
	}
	if n <= len(backoffSteps) {
		return backoffSteps[n-1]
	}
	return 30 * time.Second
}

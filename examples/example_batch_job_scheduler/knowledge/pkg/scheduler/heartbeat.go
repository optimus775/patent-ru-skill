package scheduler

import "time"

// HeartbeatConfig хранит параметры heartbeat-контракта узла.
type HeartbeatConfig struct {
	Interval    time.Duration
	DeadAfter   time.Duration // считать вероятно недоступным после такого интервала без heartbeat
}

// NodeHeartbeat хранит время последнего heartbeat.
type NodeHeartbeat struct {
	NodeID   string
	LastSeen time.Time
}

// IsProbablyDead проверяет, является ли узел вероятно недоступным.
func IsProbablyDead(h NodeHeartbeat, now time.Time, cfg HeartbeatConfig) bool {
	return now.Sub(h.LastSeen) > cfg.DeadAfter
}

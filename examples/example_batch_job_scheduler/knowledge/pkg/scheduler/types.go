// Package scheduler содержит вымышленные типы предметной области пакетного планирования.
package scheduler

import "time"

// TaskDemand представляет вектор требований задачи.
type TaskDemand struct {
	ID           string
	CPUBudget    float64 // относительный вес CPU-требования
	MemPeakMB    float64
	IOSensitive  float64 // I/O-чувствительность от 0 до 1
	MaxWait      time.Duration
	Priority     int // статический бизнес-приоритет
}

// NodeProfile представляет многомерный ресурсный профиль узла.
type NodeProfile struct {
	NodeID      string
	CPUAvail    float64 // доступная доля от 0 до 1
	MemFreeMB   float64
	IOBusy      float64 // I/O-насыщенность от 0 до 1
	Inflight    int     // выполняющиеся задачи
	UpdatedAt   time.Time
}

// MatchScore хранит score задачи на узле; большее значение лучше.
type MatchScore struct {
	TaskID  string
	NodeID  string
	Score   float64
}

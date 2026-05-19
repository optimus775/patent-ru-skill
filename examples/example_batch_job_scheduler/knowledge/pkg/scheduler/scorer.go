package scheduler

import "math"

// Score рассчитывает упрощенный score соответствия по требованиям задачи и профилю узла.
func Score(d TaskDemand, p NodeProfile) float64 {
	if p.CPUAvail <= 0 || p.MemFreeMB <= 0 {
		return -1
	}
	cpuFit := d.CPUBudget * p.CPUAvail
	memFit := math.Min(1.0, p.MemFreeMB/math.Max(1, d.MemPeakMB))
	ioFit := (1.0 - p.IOBusy) * d.IOSensitive
	inflightPenalty := float64(p.Inflight) * 0.05
	return cpuFit + memFit + ioFit - inflightPenalty
}

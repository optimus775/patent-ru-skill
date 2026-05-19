package scheduler

import "time"

// ReorderPolicy задает параметры ограниченного переупорядочивания.
type ReorderPolicy struct {
	MinInterval   time.Duration // T_r
	ScoreDelta    float64       // порог изменения распределения score
	WindowSize    int           // W
}

// reorderState хранит внутреннее состояние планировщика.
type reorderState struct {
	lastReorder time.Time
	lastScoreSig float64 // предыдущая упрощенная сигнатура score
}

// ShouldReorder проверяет пороги интервала и изменения score.
func ShouldReorder(now time.Time, p ReorderPolicy, st *reorderState, currentSig float64) bool {
	if st.lastReorder.IsZero() {
		return true
	}
	if now.Sub(st.lastReorder) < p.MinInterval {
		return false
	}
	delta := absFloat(currentSig - st.lastScoreSig)
	return delta >= p.ScoreDelta
}

func absFloat(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}

// ApplyReorder переупорядочивает окно очереди по score соответствия.
func ApplyReorder(tasks []TaskDemand, _ []NodeProfile, window int) []TaskDemand {
	if len(tasks) == 0 || window <= 0 {
		return tasks
	}
	out := make([]TaskDemand, len(tasks))
	copy(out, tasks)
	// Вымышленная заглушка: реальная реализация сортировала бы первые
	// min(window, len) задач по score; здесь сохранена форма API для анализа.
	return out
}

package managed

import (
	"errors"
	"sort"
)

type OperationKind string

const (
	DecodedFirstFlush OperationKind = "decoded_first_buffered_flush"
	DecodedRead       OperationKind = "decoded_read"
	DecodedWrite      OperationKind = "decoded_write_with_synchronous_flush"
	RemoteRead        OperationKind = "remote_read"
	RemoteWrite       OperationKind = "remote_write"
	Dial              OperationKind = "dial"
	Flush             OperationKind = "flush"
)

func validKind(kind OperationKind) bool {
	switch kind {
	case DecodedFirstFlush, DecodedRead, DecodedWrite, RemoteRead, RemoteWrite, Dial, Flush:
		return true
	}
	return false
}

// Join tracks admitted raw/flush work without adding decoded counters. These
// observations prove operation ownership only; they are not final receipts.
func (g *Gate) Join(id uint64, kind OperationKind, operation func() error) error {
	if kind == DecodedRead || kind == DecodedFirstFlush || kind == DecodedWrite || !validKind(kind) {
		return errors.New("managed_operation_kind_invalid")
	}
	profile, err := g.begin(id, kind)
	if err != nil {
		return err
	}
	operationErr := operation()
	if err = g.end(profile, id, 0, false, kind); err != nil {
		return err
	}
	return operationErr
}

type ProfileObservation struct {
	Totals               Totals                `json:"totals"`
	Phase                Phase                 `json:"phase"`
	ActiveOperations     int                   `json:"active_operations"`
	Kinds                map[OperationKind]int `json:"operation_kinds"`
	Budget               *BudgetObservation    `json:"budget,omitempty"`
	Resources            int                   `json:"resources"`
	AutomaticFreezeError string                `json:"automatic_freeze_error,omitempty"`
}
type Observation struct {
	State        string               `json:"state"`
	Epoch        string               `json:"epoch"`
	Installation Installation         `json:"installation"`
	Profiles     []ProfileObservation `json:"profiles"`
}

func (g *Gate) Observe() Observation {
	g.mu.Lock()
	defer g.mu.Unlock()
	ids := make([]int64, 0, len(g.profiles))
	for id := range g.profiles {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	result := Observation{State: "nonfinal_live_observation", Epoch: g.epoch, Installation: g.installation, Profiles: make([]ProfileObservation, 0, len(ids))}
	for _, id := range ids {
		profile := g.profiles[id]
		kinds := make(map[OperationKind]int, len(profile.kinds))
		for kind, count := range profile.kinds {
			kinds[kind] = count
		}
		item := ProfileObservation{Totals: profile.totals, Phase: profile.phase, ActiveOperations: profile.active, Kinds: kinds, AutomaticFreezeError: profile.lastAutomaticError}
		for _, session := range g.sessions {
			if session.profileID == id {
				item.Resources++
			}
		}
		if profile.budget != nil {
			value := profile.budget.observe()
			item.Budget = &value
		}
		result.Profiles = append(result.Profiles, item)
	}
	return result
}

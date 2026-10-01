// Package entitlement implements entitlement-to-Xray reconciliation. The caller is
// responsible for storing entitlements and collecting Xray's counters; this
// package makes the enforcement decision explicit and testable.
package entitlement

import (
	"context"
	"errors"
	"math"
	"strings"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

type Entitlement struct {
	XrayUser  xray.User
	ExpiresAt time.Time
	// QuotaBytes is combined uplink/downlink. A zero quota means disabled;
	// callers must use an explicit product policy rather than treating it as
	// unlimited access.
	QuotaBytes uint64
}

type Counters struct {
	UplinkBytes   uint64
	DownlinkBytes uint64
}

func (c Counters) Total() (uint64, error) {
	if math.MaxUint64-c.UplinkBytes < c.DownlinkBytes {
		return 0, errors.New("xray traffic counter overflow")
	}
	return c.UplinkBytes + c.DownlinkBytes, nil
}

type Decision string

const (
	Active         Decision = "active"
	Expired        Decision = "expired"
	QuotaExhausted Decision = "quota_exhausted"
	UsageUnknown   Decision = "usage_unknown"
)

type Result struct {
	User   xray.User
	Status Decision
	Usage  uint64
}

func Evaluate(now time.Time, entitlements []Entitlement, counters map[string]Counters) ([]xray.User, []Result, error) {
	active := make([]xray.User, 0, len(entitlements))
	results := make([]Result, 0, len(entitlements))
	seen := make(map[string]struct{}, len(entitlements))
	seenIDs := make(map[string]struct{}, len(entitlements))
	for _, entitlement := range entitlements {
		if err := entitlement.XrayUser.Validate(); err != nil {
			return nil, nil, err
		}
		email := entitlement.XrayUser.Email
		id := strings.ToLower(entitlement.XrayUser.ID)
		if _, duplicate := seen[email]; duplicate {
			return nil, nil, errors.New("duplicate entitlement statistics identifier")
		}
		seen[email] = struct{}{}
		if _, duplicate := seenIDs[id]; duplicate {
			return nil, nil, errors.New("duplicate entitlement user ID")
		}
		seenIDs[id] = struct{}{}
		counter, known := counters[email]
		usage, err := counter.Total()
		if err != nil {
			return nil, nil, err
		}
		result := Result{User: entitlement.XrayUser, Usage: usage}
		switch {
		case entitlement.ExpiresAt.IsZero() || !entitlement.ExpiresAt.After(now):
			result.Status = Expired
		case !known:
			result.Status = UsageUnknown
		case entitlement.QuotaBytes == 0 || usage >= entitlement.QuotaBytes:
			result.Status = QuotaExhausted
		default:
			result.Status = Active
			active = append(active, entitlement.XrayUser)
		}
		results = append(results, result)
	}
	return active, results, nil
}

type Applier interface {
	Apply(context.Context, []byte) error
}

type Service struct {
	Server xray.RealityServerConfig
	Store  Applier
}

// Reconcile renders only active entitlements, validates the candidate through
// the infrastructure store, and atomically reloads Xray. It never returns
// rendered JSON, which reduces the chance of exposing the node private key.
func (s Service) Reconcile(ctx context.Context, now time.Time, entitlements []Entitlement, counters map[string]Counters) ([]Result, error) {
	if s.Store == nil {
		return nil, errors.New("xray configuration applier is required")
	}
	active, results, err := Evaluate(now, entitlements, counters)
	if err != nil {
		return nil, err
	}
	contents, err := xray.RenderVLESSReality(s.Server, active)
	if err != nil {
		return nil, err
	}
	if err := s.Store.Apply(ctx, contents); err != nil {
		return nil, err
	}
	return results, nil
}

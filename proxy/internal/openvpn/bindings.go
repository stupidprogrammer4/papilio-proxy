package openvpn

import (
	"context"
	"errors"
	"sync"
)

// InstalledBindings publishes an atomic snapshot of the owning inbound's
// installed acknowledgements. It contains no private client or authority key.
type InstalledBindings struct {
	mutex sync.RWMutex
	rows  map[string]Binding
}

func (r *InstalledBindings) Replace(bindings []Binding, limit int) error {
	if limit <= 0 || len(bindings) > limit {
		return errors.New("OpenVPN binding capacity exceeded")
	}
	rows := make(map[string]Binding, len(bindings))
	profiles := make(map[int64]bool, len(bindings))
	for _, binding := range bindings {
		_, validSerial := certificateSerial(binding.SerialHex)
		if binding.ProfileID <= 0 || binding.SubscriptionID <= 0 || binding.Generation < 0 || binding.Identity == "" || !validSerial || binding.CertificateExpiresAt.IsZero() {
			return errors.New("invalid OpenVPN installed binding")
		}
		if _, exists := rows[binding.Identity]; exists || profiles[binding.ProfileID] {
			return errors.New("duplicate OpenVPN installed binding")
		}
		rows[binding.Identity], profiles[binding.ProfileID] = binding, true
	}
	r.mutex.Lock()
	defer r.mutex.Unlock()
	r.rows = rows
	return nil
}

func (r *InstalledBindings) Lookup(ctx context.Context, identity string) (Binding, error) {
	if err := ctx.Err(); err != nil {
		return Binding{}, err
	}
	r.mutex.RLock()
	defer r.mutex.RUnlock()
	binding, exists := r.rows[identity]
	if !exists {
		return Binding{}, errors.New("OpenVPN identity is not installed")
	}
	return binding, nil
}

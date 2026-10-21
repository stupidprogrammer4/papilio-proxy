package xray

import "context"

// Control exposes the native core capability to the agent transport.
type Control interface {
	UpsertVLESSUser(context.Context, VLESSUser) (bool, error)
	RemoveUser(context.Context, UserIdentity) (bool, error)
	Traffic(context.Context) (TrafficSnapshot, error)
	Status(context.Context) (RuntimeStatus, error)
}

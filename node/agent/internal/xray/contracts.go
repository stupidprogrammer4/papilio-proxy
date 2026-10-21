// Package xray adapts the official local core APIs without making business decisions.
package xray

import "errors"

var (
	ErrInvalidInput       = errors.New("invalid Xray control input")
	ErrCoreRejected       = errors.New("the Xray core rejected the operation")
	ErrCoreUnavailable    = errors.New("the local Xray API is unavailable")
	ErrUnsupportedAccount = errors.New("the account uses an unsupported Xray type")
)

type UserIdentity struct {
	InboundTag string `json:"inbound_tag"`
	Email      string `json:"email"`
}

type VLESSUser struct {
	InboundTag string `json:"inbound_tag"`
	Email      string `json:"email"`
	UUID       string `json:"uuid"`
	Flow       string `json:"flow"`
	Level      uint32 `json:"level"`
}

type Direction string

const (
	Uplink   Direction = "uplink"
	Downlink Direction = "downlink"
)

type TrafficCounter struct {
	Email     string    `json:"email"`
	Direction Direction `json:"direction"`
	Bytes     int64     `json:"bytes"`
}

// TrafficSnapshot contains observed counters only, without resetting them.
type TrafficSnapshot struct {
	Counters      []TrafficCounter `json:"counters"`
	UptimeSeconds uint32           `json:"uptime_seconds"`
}

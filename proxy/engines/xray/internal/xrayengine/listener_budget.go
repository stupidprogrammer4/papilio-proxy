package xrayengine

import (
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"strconv"
	"sync"
	"syscall"

	"github.com/xtls/xray-core/transport/internet"
)

type listenerBudget struct {
	seen      int
	effective int
	failed    bool
}
type listenerBudgets struct {
	mu         sync.Mutex
	targets    map[string]*listenerBudget
	unexpected bool
}

// This native beta controller observes only the single child's verified inbound
// listener FDs. It neither replaces a listener nor changes another process.
func installListenerBudgets(document []byte, environment *Environment) error {
	var value struct {
		Inbounds []struct {
			Listen string `json:"listen"`
			Port   uint16 `json:"port"`
		} `json:"inbounds"`
	}
	decoder := json.NewDecoder(bytes.NewReader(document))
	if decoder.Decode(&value) != nil {
		return errors.New("managed_listener_targets_invalid")
	}
	budgets := &listenerBudgets{targets: make(map[string]*listenerBudget, len(value.Inbounds))}
	for _, inbound := range value.Inbounds {
		key := net.JoinHostPort(inbound.Listen, strconv.Itoa(int(inbound.Port)))
		if budgets.targets[key] != nil {
			return errors.New("managed_listener_target_duplicate")
		}
		budgets.targets[key] = &listenerBudget{}
	}
	environment.listenerBudgets = budgets
	return internet.RegisterListenerController(func(network, address string, raw syscall.RawConn) error {
		budgets.mu.Lock()
		defer budgets.mu.Unlock()
		target := budgets.targets[address]
		if target == nil || (network != "tcp" && network != "tcp4" && network != "tcp6") {
			budgets.unexpected = true
			return errors.New("managed_listener_target_unavailable")
		}
		target.seen++
		controlErr := raw.Control(func(fd uintptr) {
			if syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_SNDBUF, environment.Policy.TCPListenerSendBufferBytes) != nil {
				target.failed = true
				return
			}
			effective, err := syscall.GetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_SNDBUF)
			if err != nil {
				target.failed = true
				return
			}
			target.effective = effective
		})
		if controlErr != nil {
			target.failed = true
		}
		if target.failed {
			return errors.New("managed_listener_budget_failed")
		}
		return nil
	})
}

// Xray logs-and-continues when a controller fails. The owning child must call
// this after native Start and before ready/control exposure, then stop on error.
func VerifyListenerBudgets(environment *Environment) error {
	if environment == nil || environment.listenerBudgets == nil {
		return errors.New("managed_listener_budget_unobserved")
	}
	budgets := environment.listenerBudgets
	budgets.mu.Lock()
	defer budgets.mu.Unlock()
	if budgets.unexpected || len(budgets.targets) == 0 {
		return errors.New("managed_listener_budget_unobserved")
	}
	for _, target := range budgets.targets {
		if target.seen != 1 || target.failed || target.effective < environment.Policy.TCPListenerMinEffectiveSendBufferBytes || target.effective > environment.Policy.TCPListenerMaxEffectiveSendBufferBytes {
			return errors.New("managed_listener_budget_mismatch")
		}
	}
	return nil
}

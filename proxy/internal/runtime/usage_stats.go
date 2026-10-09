package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os/exec"
	"regexp"
	"strconv"
	"syscall"
	"time"
)

var counterIdentityPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)

// StatsPolicy is a local execution budget. Remote documents cannot supply
// executable paths, extra flags, or remotely reachable management endpoints.
type StatsPolicy struct {
	Timeout        time.Duration
	StopTimeout    time.Duration
	MaxOutputBytes int64
}

type XrayStats struct {
	binary string
	policy StatsPolicy
}

func NewXrayStats(registry BinaryRegistry, policy StatsPolicy) (*XrayStats, error) {
	if policy.Timeout <= 0 || policy.StopTimeout <= 0 || policy.MaxOutputBytes <= 0 {
		return nil, errors.New("usage_stats_capacity_invalid")
	}
	binary, err := registry.binary("xray")
	if err != nil {
		return nil, err
	}
	return &XrayStats{binary: binary, policy: policy}, nil
}

// Counter reads a cumulative counter without resetting it. Missing counters
// are unavailable evidence; they are never invented as zero.
func (s *XrayStats) Counter(ctx context.Context, address string, port int, identity, direction string) (int64, error) {
	ip := net.ParseIP(address)
	if ip == nil || !ip.Equal(net.IPv4(127, 0, 0, 1)) || port <= 0 || port > 65535 || !counterIdentityPattern.MatchString(identity) || (direction != "uplink" && direction != "downlink") {
		return 0, errors.New("usage_stats_binding_invalid")
	}
	name := "user>>>" + identity + ">>>traffic>>>" + direction
	payload, err := s.execute(ctx, address, port, "stats", "-name="+name)
	if err != nil {
		return 0, err
	}
	var response struct {
		Stat *struct {
			Name  string          `json:"name"`
			Value json.RawMessage `json:"value"`
		} `json:"stat"`
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&response) != nil || response.Stat == nil || response.Stat.Name != name {
		return 0, errors.New("usage_stats_response_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return 0, errors.New("usage_stats_response_invalid")
	}
	return decodeStatsValue(response.Stat.Value)
}

func (s *XrayStats) execute(ctx context.Context, address string, port int, commandName, selector string) ([]byte, error) {
	operation, cancel := context.WithTimeout(ctx, s.policy.Timeout)
	defer cancel()
	seconds := s.policy.Timeout / time.Second
	if s.policy.Timeout%time.Second != 0 {
		seconds++
	}
	command := exec.CommandContext(operation, s.binary, "api", commandName, "-server="+net.JoinHostPort(address, strconv.Itoa(port)), "-timeout="+strconv.FormatInt(int64(seconds), 10), selector)
	output := &boundedStatsOutput{limit: s.policy.MaxOutputBytes, cancel: cancel}
	command.Stdout = output
	command.Stderr = io.Discard
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	command.WaitDelay = s.policy.StopTimeout
	command.Cancel = func() error {
		if command.Process == nil {
			return nil
		}
		err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return nil
		}
		return err
	}
	err := command.Run()
	if output.overflow {
		return nil, errors.New("usage_stats_output_capacity")
	}
	if err != nil {
		return nil, errors.New("usage_stats_unavailable")
	}
	return output.buffer.Bytes(), nil
}

type CounterPair struct {
	Upload   *int64
	Download *int64
}

// Counters queries only one opaque user's prefix. Nil values distinguish lazy
// initial counters from observed zeros; callers must enforce epoch continuity.
func (s *XrayStats) Counters(ctx context.Context, address string, port int, identity string) (CounterPair, error) {
	if address != "127.0.0.1" || port <= 0 || port > 65535 || !counterIdentityPattern.MatchString(identity) {
		return CounterPair{}, errors.New("usage_stats_binding_invalid")
	}
	prefix := "user>>>" + identity + ">>>traffic>>>"
	payload, err := s.execute(ctx, address, port, "statsquery", "-pattern="+prefix)
	if err != nil {
		return CounterPair{}, err
	}
	var response struct {
		Stat []struct {
			Name  string          `json:"name"`
			Value json.RawMessage `json:"value"`
		} `json:"stat"`
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&response) != nil || len(response.Stat) > 2 {
		return CounterPair{}, errors.New("usage_stats_response_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return CounterPair{}, errors.New("usage_stats_response_invalid")
	}
	var result CounterPair
	for _, stat := range response.Stat {
		value, parseErr := decodeStatsValue(stat.Value)
		if parseErr != nil {
			return CounterPair{}, parseErr
		}
		switch stat.Name {
		case prefix + "uplink":
			if result.Upload != nil {
				return CounterPair{}, errors.New("usage_stats_response_invalid")
			}
			result.Upload = &value
		case prefix + "downlink":
			if result.Download != nil {
				return CounterPair{}, errors.New("usage_stats_response_invalid")
			}
			result.Download = &value
		default:
			return CounterPair{}, errors.New("usage_stats_response_invalid")
		}
	}
	return result, nil
}

func decodeStatsValue(raw json.RawMessage) (int64, error) {
	value := string(raw)
	// The pinned Xray CLI omits protobuf zero values. A returned exact Stat
	// proves the counter exists; an absent Stat or failed RPC never proves zero.
	if len(raw) == 0 {
		return 0, nil
	}
	if len(value) > 0 && value[0] == '"' {
		if json.Unmarshal(raw, &value) != nil {
			return 0, errors.New("usage_stats_response_invalid")
		}
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed < 0 {
		return 0, errors.New("usage_stats_response_invalid")
	}
	return parsed, nil
}

type boundedStatsOutput struct {
	buffer   bytes.Buffer
	limit    int64
	cancel   context.CancelFunc
	overflow bool
}

func (w *boundedStatsOutput) Write(payload []byte) (int, error) {
	if int64(w.buffer.Len())+int64(len(payload)) > w.limit {
		w.overflow = true
		w.cancel()
		return 0, errors.New("usage_stats_output_capacity")
	}
	return w.buffer.Write(payload)
}

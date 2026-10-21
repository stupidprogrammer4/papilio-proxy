package xray

import (
	"context"
	"net"
	"strconv"
	"strings"

	"github.com/xtls/xray-core/app/proxyman/command"
	statscommand "github.com/xtls/xray-core/app/stats/command"
	"github.com/xtls/xray-core/common/protocol"
	"github.com/xtls/xray-core/common/serial"
	"github.com/xtls/xray-core/proxy/vless"
	"golang.org/x/sync/semaphore"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

// Client serializes one core's read/alter user operations. It does not emulate a batch API.
type Client struct {
	connection *grpc.ClientConn
	handler    command.HandlerServiceClient
	statistics statscommand.StatsServiceClient
	mutations  *semaphore.Weighted
}

// Dial accepts loopback IPs only; the agent's remote control channel uses mTLS.
func Dial(options ConnectionOptions) (*Client, error) {
	address := options.Address
	if options.MaxReplyBytes <= 0 {
		return nil, ErrInvalidInput
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, ErrInvalidInput
	}
	ip := net.ParseIP(host)
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 || ip == nil || !ip.IsLoopback() {
		return nil, ErrInvalidInput
	}
	connection, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(options.MaxReplyBytes)))
	if err != nil {
		return nil, ErrCoreUnavailable
	}
	return &Client{connection: connection, handler: command.NewHandlerServiceClient(connection), statistics: statscommand.NewStatsServiceClient(connection), mutations: semaphore.NewWeighted(1)}, nil
}

func (client *Client) Close() error {
	return client.connection.Close()
}

func coreError(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if status.Code(err) == codes.Unavailable {
		return ErrCoreUnavailable
	}
	if status.Code(err) == codes.ResourceExhausted {
		return ErrCoreResourceLimit
	}
	return ErrCoreRejected
}

func (client *Client) findUser(ctx context.Context, identity UserIdentity) (*protocol.User, error) {
	result, err := client.handler.GetInboundUsers(ctx, &command.GetInboundUserRequest{Tag: identity.InboundTag, Email: identity.Email})
	if err != nil {
		return nil, coreError(ctx, err)
	}
	for _, user := range result.Users {
		if user != nil && user.Email == identity.Email {
			return user, nil
		}
	}
	return nil, nil
}

func (client *Client) remove(ctx context.Context, identity UserIdentity) error {
	_, err := client.handler.AlterInbound(ctx, &command.AlterInboundRequest{
		Tag:       identity.InboundTag,
		Operation: serial.ToTypedMessage(&command.RemoveUserOperation{Email: identity.Email}),
	})
	if err != nil {
		return coreError(ctx, err)
	}
	return nil
}

// UpsertVLESSUser reconciles the named account; an identical replay does no write.
func (client *Client) UpsertVLESSUser(ctx context.Context, user VLESSUser) (bool, error) {
	account, err := validatedAccount(user)
	if err != nil {
		return false, err
	}
	if err := client.mutations.Acquire(ctx, 1); err != nil {
		return false, err
	}
	defer client.mutations.Release(1)
	identity := UserIdentity{InboundTag: user.InboundTag, Email: user.Email}
	existing, err := client.findUser(ctx, identity)
	if err != nil {
		return false, err
	}
	if existing != nil {
		if existing.Account == nil {
			return false, ErrUnsupportedAccount
		}
		message, err := existing.Account.GetInstance()
		if err != nil {
			return false, ErrUnsupportedAccount
		}
		previous, ok := message.(*vless.Account)
		if !ok {
			return false, ErrUnsupportedAccount
		}
		if existing.Level == user.Level && proto.Equal(previous, account) {
			return false, nil
		}
		if err := client.remove(ctx, identity); err != nil {
			return false, err
		}
	}
	_, err = client.handler.AlterInbound(ctx, &command.AlterInboundRequest{
		Tag: user.InboundTag,
		Operation: serial.ToTypedMessage(&command.AddUserOperation{User: &protocol.User{
			Email: user.Email, Level: user.Level, Account: serial.ToTypedMessage(account),
		}}),
	})
	if err != nil {
		return false, coreError(ctx, err)
	}
	return true, nil
}

// RemoveUser is idempotent for an absent named user and rejects missing inbounds.
func (client *Client) RemoveUser(ctx context.Context, identity UserIdentity) (bool, error) {
	if err := validateIdentity(identity); err != nil {
		return false, err
	}
	if err := client.mutations.Acquire(ctx, 1); err != nil {
		return false, err
	}
	defer client.mutations.Release(1)
	existing, err := client.findUser(ctx, identity)
	if err != nil {
		return false, err
	}
	if existing == nil {
		return false, nil
	}
	if err := client.remove(ctx, identity); err != nil {
		return false, err
	}
	return true, nil
}

// Traffic uses two native aggregate reads, independent of the number of users.
func (client *Client) Traffic(ctx context.Context) (TrafficSnapshot, error) {
	result, err := client.statistics.QueryStats(ctx, &statscommand.QueryStatsRequest{Pattern: "user>>>"})
	if err != nil {
		return TrafficSnapshot{}, coreError(ctx, err)
	}
	system, err := client.Status(ctx)
	if err != nil {
		return TrafficSnapshot{}, err
	}
	snapshot := TrafficSnapshot{Counters: make([]TrafficCounter, 0, len(result.Stat)), UptimeSeconds: system.UptimeSeconds}
	for _, stat := range result.Stat {
		parts := strings.Split(stat.Name, ">>>")
		if len(parts) != 4 || parts[0] != "user" || parts[2] != "traffic" {
			continue
		}
		direction := Direction(parts[3])
		if direction != Uplink && direction != Downlink {
			continue
		}
		snapshot.Counters = append(snapshot.Counters, TrafficCounter{Email: parts[1], Direction: direction, Bytes: stat.Value})
	}
	return snapshot, nil
}

func (client *Client) Status(ctx context.Context) (RuntimeStatus, error) {
	system, err := client.statistics.GetSysStats(ctx, &statscommand.SysStatsRequest{})
	if err != nil {
		return RuntimeStatus{}, coreError(ctx, err)
	}
	return RuntimeStatus{UptimeSeconds: system.Uptime}, nil
}

package xrayengine

import (
	"context"
	"errors"
	"sync"

	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/serial"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/dynamicpb"
)

const dispatcherFullName protoreflect.FullName = "papilio.managed.xray.DispatcherConfig"

var registerOnce sync.Once
var registerError error
var dispatcherMessageType protoreflect.MessageType

// Register owns exactly one dynamic native config type. No generic dynamic
// config dispatch is accepted by the creator; other full names fail closed.
func Register() error {
	registerOnce.Do(func() {
		file, err := protodesc.NewFile(&descriptorpb.FileDescriptorProto{
			Name:    proto.String("papilio/managed_xray/dispatcher.proto"),
			Package: proto.String("papilio.managed.xray"), Syntax: proto.String("proto3"),
			MessageType: []*descriptorpb.DescriptorProto{{Name: proto.String("DispatcherConfig")}},
		}, nil)
		if err != nil {
			registerError = errors.New("managed_registration_invalid")
			return
		}
		dispatcherMessageType = dynamicpb.NewMessageType(file.Messages().Get(0))
		if err = protoregistry.GlobalTypes.RegisterMessage(dispatcherMessageType); err != nil {
			registerError = errors.New("managed_registration_conflict")
			return
		}
		registerError = common.RegisterConfig((*dynamicpb.Message)(nil), func(ctx context.Context, config interface{}) (interface{}, error) {
			message, ok := config.(*dynamicpb.Message)
			if !ok || message.Descriptor().FullName() != dispatcherFullName {
				return nil, errors.New("managed_registration_type_invalid")
			}
			environment, ok := ctx.Value(environmentKey{}).(*Environment)
			if !ok || environment == nil {
				return nil, errors.New("managed_environment_missing")
			}
			return newDispatcher(ctx, environment)
		})
	})
	return registerError
}
func DispatcherApp() (*serial.TypedMessage, error) {
	if err := Register(); err != nil {
		return nil, err
	}
	return serial.ToTypedMessage(dispatcherMessageType.New().Interface()), nil
}

type environmentKey struct{}

func Context(ctx context.Context, environment *Environment) context.Context {
	return context.WithValue(ctx, environmentKey{}, environment)
}

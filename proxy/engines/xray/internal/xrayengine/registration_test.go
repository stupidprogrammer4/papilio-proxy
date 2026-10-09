package xrayengine

import (
	"context"
	"testing"

	"github.com/xtls/xray-core/common"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/dynamicpb"
)

func TestNativeDescriptorResolvesAndRejectsOtherDynamicConfig(t *testing.T) {
	app, err := DispatcherApp()
	if err != nil {
		t.Fatal(err)
	}
	again, err := DispatcherApp()
	if err != nil || again.Type != app.Type {
		t.Fatal("native registration changed", err)
	}
	instance, err := app.GetInstance()
	if err != nil {
		t.Fatal(err)
	}
	if instance.ProtoReflect().Descriptor().FullName() != dispatcherFullName {
		t.Fatal("native descriptor full name mismatch")
	}
	if _, err = common.CreateObject(context.Background(), instance); err == nil {
		t.Fatal("missing owned environment accepted")
	}
	other, err := protodesc.NewFile(&descriptorpb.FileDescriptorProto{Name: proto.String("owned-other.proto"), Package: proto.String("papilio.other"), Syntax: proto.String("proto3"), MessageType: []*descriptorpb.DescriptorProto{{Name: proto.String("UntrustedConfig")}}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	dynamic := dynamicpb.NewMessage(other.Messages().Get(0))
	if _, err = common.CreateObject(context.Background(), dynamic); err == nil || err.Error() != "managed_registration_type_invalid" {
		t.Fatal("generic dynamic config creator accepted", err)
	}
}

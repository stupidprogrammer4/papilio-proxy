package xray

import (
	"strings"

	"github.com/google/uuid"
	"github.com/xtls/xray-core/proxy/vless"
)

func validateIdentity(identity UserIdentity) error {
	if identity.InboundTag == "" || strings.TrimSpace(identity.InboundTag) != identity.InboundTag {
		return ErrInvalidInput
	}
	if identity.Email == "" || strings.TrimSpace(identity.Email) != identity.Email || strings.ToLower(identity.Email) != identity.Email || strings.Contains(identity.Email, ">>>") {
		return ErrInvalidInput
	}
	return nil
}

func validatedAccount(user VLESSUser) (*vless.Account, error) {
	if err := validateIdentity(UserIdentity{InboundTag: user.InboundTag, Email: user.Email}); err != nil {
		return nil, err
	}
	identifier, err := uuid.Parse(user.UUID)
	if err != nil {
		return nil, ErrInvalidInput
	}
	if user.Flow != "" && user.Flow != "xtls-rprx-vision" {
		return nil, ErrInvalidInput
	}
	return &vless.Account{Id: identifier.String(), Flow: user.Flow, Encryption: "none"}, nil
}

package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"

	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

type renderInput struct {
	Server xray.DualServerConfig `json:"server"`
	Users  []xray.User           `json:"users"`
}

func renderConfig(input io.Reader, output io.Writer) error {
	decoder := json.NewDecoder(io.LimitReader(input, 1<<20))
	decoder.DisallowUnknownFields()
	var request renderInput
	if err := decoder.Decode(&request); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return errors.New("unexpected trailing configuration data")
	}
	config, err := xray.RenderDualProtocol(request.Server, request.Users)
	if err != nil {
		return err
	}
	_, err = output.Write(append(config, '\n'))
	return err
}

func runRender() error {
	return renderConfig(os.Stdin, os.Stdout)
}

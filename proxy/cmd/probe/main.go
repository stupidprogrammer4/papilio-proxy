package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"time"

	"papilio-proxy/proxy/internal/probe"
	"papilio-proxy/proxy/internal/report"
)

type config struct {
	APIURL                 string `json:"api_url"`
	NodeCode               string `json:"node_code"`
	PublicHost             string `json:"public_host"`
	PublicPort             int    `json:"public_port"`
	Protocol               string `json:"protocol"`
	TLSServerName          string `json:"tls_server_name"`
	ClientNetwork          string `json:"client_network"`
	ConnectTimeoutMS       int    `json:"connect_timeout_ms"`
	ReportTimeoutMS        int    `json:"report_timeout_ms"`
	ReportMaxResponseBytes int64  `json:"report_max_response_bytes"`
}

func run(ctx context.Context, path string) error {
	key := os.Getenv("PAPILIO_NODE_KEY")
	if key == "" {
		return errors.New("PAPILIO_NODE_KEY is required")
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	var settings config
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&settings); err != nil {
		return err
	}
	if settings.NodeCode == "" || settings.ClientNetwork == "" || settings.ConnectTimeoutMS <= 0 || settings.ReportTimeoutMS <= 0 || settings.ReportMaxResponseBytes <= 0 {
		return errors.New("node code, client network and timeouts are required")
	}
	address, err := url.Parse(settings.APIURL)
	if err != nil || address.Host == "" || (address.Scheme != "https" && address.Scheme != "http") {
		return errors.New("valid API URL is required")
	}
	measured, err := probe.Measure(ctx, probe.Endpoint{Host: settings.PublicHost, Port: settings.PublicPort, Protocol: settings.Protocol, TLSServerName: settings.TLSServerName}, time.Duration(settings.ConnectTimeoutMS)*time.Millisecond)
	if err != nil {
		return err
	}
	id := make([]byte, 16)
	if _, err := rand.Read(id); err != nil {
		return err
	}
	client := report.Client{BaseURL: address, Key: key, MaxResponseBytes: settings.ReportMaxResponseBytes, HTTP: &http.Client{Timeout: time.Duration(settings.ReportTimeoutMS) * time.Millisecond}}
	event := report.Event{EventID: hex.EncodeToString(id), ClientNetwork: settings.ClientNetwork, Success: measured.Success, LatencyMS: measured.LatencyMS, SampledAt: time.Now().UTC()}
	return client.Send(ctx, settings.NodeCode, event)
}

func main() {
	path := flag.String("config", "", "path to private probe configuration")
	flag.Parse()
	if *path == "" {
		fmt.Fprintln(os.Stderr, "-config is required")
		os.Exit(2)
	}
	if err := run(context.Background(), *path); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

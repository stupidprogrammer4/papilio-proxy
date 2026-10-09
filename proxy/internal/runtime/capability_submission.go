package runtime

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

type CapabilitySubmissionPolicy struct {
	Enabled         bool   `json:"enabled"`
	StateDirectory  string `json:"state_directory"`
	MaxPendingBytes int64  `json:"max_pending_bytes"`
	MaxReportBytes  int64  `json:"max_report_bytes"`
}
type CapabilitySubmission struct {
	ReportID     string           `json:"report_id"`
	ReportSHA256 string           `json:"report_sha256"`
	Report       CapabilityReport `json:"report"`
}
type CapabilityReceipt struct {
	ObservationID int64     `json:"observation_id"`
	NodeID        int64     `json:"node_id"`
	NodeCode      string    `json:"node_code"`
	ReportID      string    `json:"report_id"`
	ReportSHA256  string    `json:"report_sha256"`
	ObservedAt    time.Time `json:"observed_at"`
	ReceivedAt    time.Time `json:"received_at"`
}
type capabilityPending struct {
	NodeCode   string               `json:"node_code"`
	APIURL     string               `json:"api_url"`
	Submission CapabilitySubmission `json:"submission"`
	Receipt    *CapabilityReceipt   `json:"receipt"`
}
type CapabilityPublisher struct {
	client *Client
	policy CapabilitySubmissionPolicy
	lock   *os.File
}
type capabilityCanonicalReport struct {
	CapabilityReport
	ObservedAt string `json:"observed_at"`
}

func capabilityCanonical(report CapabilityReport) ([]byte, error) {
	payload, err := json.Marshal(capabilityCanonicalReport{CapabilityReport: report, ObservedAt: report.ObservedAt.UTC().Truncate(time.Microsecond).Format("2006-01-02T15:04:05.000000Z")})
	if err != nil {
		return nil, errors.New("capability_report_encoding_failed")
	}
	return canonicalJSON(payload)
}
func NewCapabilityPublisher(client *Client, policy CapabilitySubmissionPolicy) (*CapabilityPublisher, error) {
	if client == nil || !policy.Enabled || !filepath.IsAbs(policy.StateDirectory) || policy.MaxPendingBytes <= 0 || policy.MaxPendingBytes >= math.MaxInt64 || policy.MaxReportBytes <= 0 || policy.MaxReportBytes > policy.MaxPendingBytes {
		return nil, errors.New("capability_submission_policy_invalid")
	}
	root := policy.StateDirectory
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, errors.New("capability_outbox_unavailable")
	}
	info, err := os.Lstat(root)
	resolved, resolveErr := filepath.EvalSymlinks(root)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 || resolveErr != nil || resolved != filepath.Clean(root) {
		return nil, errors.New("capability_outbox_unsafe")
	}
	lock, err := os.OpenFile(filepath.Join(root, "capability.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0600)
	if err != nil {
		return nil, errors.New("capability_outbox_lock_unavailable")
	}
	info, err = lock.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		lock.Close()
		return nil, errors.New("capability_outbox_lock_unsafe")
	}
	lockStat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || lockStat.Nlink != 1 || lockStat.Uid != uint32(os.Getuid()) {
		lock.Close()
		return nil, errors.New("capability_outbox_lock_unsafe")
	}
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, errors.New("capability_outbox_owned")
	}
	return &CapabilityPublisher{client: client, policy: policy, lock: lock}, nil
}
func (p *CapabilityPublisher) Close() error { return p.lock.Close() }
func (p *CapabilityPublisher) read() (*capabilityPending, error) {
	file, err := os.OpenFile(filepath.Join(p.policy.StateDirectory, "pending.json"), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, errors.New("capability_pending_unavailable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("capability_pending_unsafe")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Nlink != 1 || stat.Uid != uint32(os.Getuid()) {
		return nil, errors.New("capability_pending_unsafe")
	}
	payload, err := io.ReadAll(io.LimitReader(file, p.policy.MaxPendingBytes+1))
	if err != nil || int64(len(payload)) > p.policy.MaxPendingBytes {
		return nil, errors.New("capability_pending_capacity")
	}
	var pending capabilityPending
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&pending) != nil {
		return nil, errors.New("capability_pending_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return nil, errors.New("capability_pending_invalid")
	}
	if pending.NodeCode != p.client.config.NodeCode || pending.APIURL != p.client.config.APIURL || !epochPattern.MatchString(pending.Submission.ReportID) {
		return nil, errors.New("capability_pending_identity_invalid")
	}
	canonical, err := capabilityCanonical(pending.Submission.Report)
	if err != nil || !digestPattern.MatchString(pending.Submission.ReportSHA256) || checksum(canonical) != pending.Submission.ReportSHA256 {
		return nil, errors.New("capability_pending_digest_invalid")
	}
	if pending.Receipt != nil && !validCapabilityReceipt(*pending.Receipt, pending.Submission, p.client.config.NodeCode) {
		return nil, errors.New("capability_pending_receipt_invalid")
	}
	return &pending, nil
}
func (p *CapabilityPublisher) save(pending capabilityPending) error {
	payload, err := json.Marshal(pending)
	if err != nil || int64(len(payload)) > p.policy.MaxPendingBytes {
		return errors.New("capability_pending_capacity")
	}
	return atomicPrivate(p.policy.StateDirectory, "pending.json", payload)
}
func validCapabilityReceipt(receipt CapabilityReceipt, submission CapabilitySubmission, code string) bool {
	return receipt.ObservationID > 0 && receipt.NodeID > 0 && receipt.NodeCode == code && receipt.ReportID == submission.ReportID && receipt.ReportSHA256 == submission.ReportSHA256 && receipt.ObservedAt.Equal(submission.Report.ObservedAt) && !receipt.ReceivedAt.IsZero()
}
func (c *Client) PublishCapabilities(ctx context.Context, submission CapabilitySubmission) (CapabilityReceipt, error) {
	var response struct {
		Success bool              `json:"success"`
		Data    CapabilityReceipt `json:"data"`
	}
	if !epochPattern.MatchString(submission.ReportID) || !digestPattern.MatchString(submission.ReportSHA256) {
		return CapabilityReceipt{}, errors.New("capability_submission_identity_invalid")
	}
	err := c.request(ctx, http.MethodPost, "/capability-observations", submission, &response)
	if err != nil {
		return CapabilityReceipt{}, err
	}
	if !response.Success || !validCapabilityReceipt(response.Data, submission, c.config.NodeCode) {
		return CapabilityReceipt{}, errors.New("capability_receipt_invalid")
	}
	return response.Data, nil
}

// Publish retries the immutable pending body before observing another binary.
func (p *CapabilityPublisher) Publish(ctx context.Context, reporter *CapabilityReporter) (CapabilityReceipt, error) {
	pending, err := p.read()
	if err != nil {
		return CapabilityReceipt{}, err
	}
	if pending == nil {
		if reporter == nil {
			return CapabilityReceipt{}, errors.New("capability_reporter_required")
		}
		report := reporter.Report(ctx)
		report.ObservedAt = report.ObservedAt.UTC().Truncate(time.Microsecond)
		if ctx.Err() != nil {
			return CapabilityReceipt{}, errors.New("capability_submission_cancelled")
		}
		canonical, err := capabilityCanonical(report)
		if err != nil || int64(len(canonical)) > p.policy.MaxReportBytes {
			return CapabilityReceipt{}, errors.New("capability_report_capacity")
		}
		var identity [16]byte
		if _, err = rand.Read(identity[:]); err != nil {
			return CapabilityReceipt{}, errors.New("capability_submission_identity_unavailable")
		}
		pending = &capabilityPending{NodeCode: p.client.config.NodeCode, APIURL: p.client.config.APIURL, Submission: CapabilitySubmission{ReportID: hex.EncodeToString(identity[:]), ReportSHA256: checksum(canonical), Report: report}}
		trial := *pending
		trial.Receipt = &CapabilityReceipt{ObservationID: math.MaxInt64, NodeID: math.MaxInt64, NodeCode: p.client.config.NodeCode, ReportID: pending.Submission.ReportID, ReportSHA256: pending.Submission.ReportSHA256, ObservedAt: report.ObservedAt, ReceivedAt: time.Date(9999, 12, 31, 23, 59, 59, 999999000, time.UTC)}
		encodedTrial, trialErr := json.Marshal(trial)
		if trialErr != nil || int64(len(encodedTrial)) > p.policy.MaxPendingBytes {
			return CapabilityReceipt{}, errors.New("capability_pending_capacity")
		}
		if err = p.save(*pending); err != nil {
			return CapabilityReceipt{}, err
		}
	}
	if pending.Receipt != nil {
		return *pending.Receipt, nil
	}
	receipt, err := p.client.PublishCapabilities(ctx, pending.Submission)
	if err != nil {
		return CapabilityReceipt{}, err
	}
	pending.Receipt = &receipt
	if err = p.save(*pending); err != nil {
		return CapabilityReceipt{}, err
	}
	return receipt, nil
}

// ClearAcknowledged is called only after the receipt reaches the CLI consumer.
func (p *CapabilityPublisher) ClearAcknowledged() error {
	pending, err := p.read()
	if err != nil {
		return err
	}
	if pending == nil || pending.Receipt == nil {
		return errors.New("capability_receipt_not_persisted")
	}
	if err = os.Remove(filepath.Join(p.policy.StateDirectory, "pending.json")); err != nil {
		return errors.New("capability_receipt_cleanup_failed")
	}
	directory, err := os.Open(p.policy.StateDirectory)
	if err != nil {
		return errors.New("capability_receipt_cleanup_failed")
	}
	defer directory.Close()
	if directory.Sync() != nil {
		return errors.New("capability_receipt_cleanup_failed")
	}
	return nil
}

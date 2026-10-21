package control

import (
	"context"
	"errors"
	"net"
	"net/http"
	"time"
)

// Serve owns the native TLS server's bounded shutdown and forced cleanup.
func Serve(ctx context.Context, server *http.Server, listener net.Listener, shutdownTimeout time.Duration) error {
	result := make(chan error, 1)
	go func() { result <- server.ServeTLS(listener, "", "") }()
	select {
	case err := <-result:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdown); err != nil {
		_ = server.Close()
		<-result
		return err
	}
	err := <-result
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

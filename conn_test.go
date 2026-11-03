package main

import (
	"errors"
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	ber "github.com/go-asn1-ber/asn1-ber"
	"github.com/go-ldap/ldap/v3"
)

// newPipeConn returns a live *ldap.Conn backed by an in-memory pipe, plus the
// peer end so the caller can keep it open. It never speaks LDAP; it exists so
// tests can exercise connection bookkeeping with real, closable Conn values.
func newPipeConn(t *testing.T) *ldap.Conn {
	t.Helper()
	client, server := net.Pipe()
	t.Cleanup(func() { server.Close() })

	l := ldap.NewConn(client, false)
	l.Start()
	return l
}

// resetSourceConn clears the shared connection without closing it, so tests
// start from a known state and don't leak state into each other.
func resetSourceConn(t *testing.T) {
	t.Helper()
	clear := func() {
		sourceConnMu.Lock()
		sourceConn = nil
		sourceErr = nil
		sourceRetryAt = time.Time{}
		sourceBackoff = 0
		sourceConnMu.Unlock()
	}
	t.Cleanup(clear)
	clear()
}

func TestIsConnectionError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{"network error", ldap.NewError(ldap.ErrorNetwork, errors.New("broken pipe")), true},
		{"unexpected message", ldap.NewError(ldap.ErrorUnexpectedMessage, errors.New("x")), true},
		{"unexpected response", ldap.NewError(ldap.ErrorUnexpectedResponse, errors.New("x")), true},
		{"no such object", ldap.NewError(ldap.LDAPResultNoSuchObject, errors.New("x")), false},
		{"size limit exceeded", ldap.NewError(ldap.LDAPResultSizeLimitExceeded, errors.New("x")), false},
		{"invalid credentials", ldap.NewError(ldap.LDAPResultInvalidCredentials, errors.New("x")), false},
		{"non-ldap error", errors.New("dial tcp: timeout"), true},
		{"wrapped network error", fmt.Errorf("search failed: %w", ldap.NewError(ldap.ErrorNetwork, errors.New("x"))), true},
		{"wrapped server error", fmt.Errorf("search failed: %w", ldap.NewError(ldap.LDAPResultNoSuchObject, errors.New("x"))), false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := isConnectionError(tt.err); got != tt.want {
				t.Errorf("isConnectionError(%v) = %v, want %v", tt.err, got, tt.want)
			}
		})
	}
}

func TestDropSourceConn_ClearsMatching(t *testing.T) {
	resetSourceConn(t)

	l := newPipeConn(t)
	sourceConnMu.Lock()
	sourceConn = l
	sourceConnMu.Unlock()

	dropSourceConn(l)

	sourceConnMu.Lock()
	got := sourceConn
	sourceConnMu.Unlock()
	if got != nil {
		t.Error("dropSourceConn did not clear the shared connection")
	}
}

// Two goroutines can fail on the same stale connection concurrently. The first
// drops and the second redials; the straggler's drop must not discard the
// fresh connection the second one installed.
func TestDropSourceConn_IgnoresReplacement(t *testing.T) {
	resetSourceConn(t)

	stale := newPipeConn(t)
	fresh := newPipeConn(t)

	sourceConnMu.Lock()
	sourceConn = stale
	sourceConnMu.Unlock()

	dropSourceConn(stale) // first goroutine notices the failure

	sourceConnMu.Lock()
	sourceConn = fresh // second goroutine redials
	sourceConnMu.Unlock()

	dropSourceConn(stale) // straggler reports the same stale failure

	sourceConnMu.Lock()
	got := sourceConn
	sourceConnMu.Unlock()
	if got != fresh {
		t.Error("straggler discarded the replacement connection")
	}
}

// A closed connection must not be handed out again.
func TestGetSourceConn_RejectsClosedConn(t *testing.T) {
	resetSourceConn(t)

	l := newPipeConn(t)
	l.Close()

	sourceConnMu.Lock()
	sourceConn = l
	sourceConnMu.Unlock()

	if !l.IsClosing() {
		t.Fatal("precondition: connection should report as closing")
	}

	// config.Source.URL is unset, so the redial fails; the point is that
	// getSourceConn attempts one rather than returning the dead connection.
	got, err := getSourceConn()
	if err == nil && got == l {
		t.Error("getSourceConn returned a closed connection")
	}
}

// countingListener accepts TCP connections and closes them immediately, so
// every dial reaches it but every bind fails. It reports how many dials arrived.
func countingListener(t *testing.T) (string, *atomic.Int32) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })

	var dials atomic.Int32
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			dials.Add(1)
			c.Close()
		}
	}()
	return "ldap://" + ln.Addr().String(), &dials
}

// After a failed connect, callers must not each trigger their own dial and
// bind until the backoff expires.
func TestGetSourceConn_BackoffSuppressesRedial(t *testing.T) {
	resetSourceConn(t)
	url, dials := countingListener(t)
	prev := config.Source
	config.Source.URL = url
	config.Source.BindDN = "cn=svc"
	config.Source.BindPassword = "secret"
	t.Cleanup(func() { config.Source = prev })

	waitForDials := func(want int32) {
		t.Helper()
		deadline := time.Now().Add(2 * time.Second)
		for dials.Load() < want && time.Now().Before(deadline) {
			time.Sleep(5 * time.Millisecond)
		}
		if got := dials.Load(); got != want {
			t.Fatalf("dial attempts = %d, want %d", got, want)
		}
	}

	if _, err := getSourceConn(); err == nil {
		t.Fatal("expected first connect to fail")
	}
	waitForDials(1)
	for i := 0; i < 20; i++ {
		if _, err := getSourceConn(); err == nil {
			t.Fatal("expected error during backoff")
		}
	}
	time.Sleep(50 * time.Millisecond)
	waitForDials(1)

	sourceConnMu.Lock()
	sourceRetryAt = time.Now().Add(-time.Second)
	sourceConnMu.Unlock()

	getSourceConn()
	waitForDials(2)

	sourceConnMu.Lock()
	backoff := sourceBackoff
	sourceConnMu.Unlock()
	if backoff != 2*sourceBackoffInitial {
		t.Errorf("backoff after second failure = %s, want %s", backoff, 2*sourceBackoffInitial)
	}
}

func TestNextSourceBackoff(t *testing.T) {
	netErr := ldap.NewError(ldap.ErrorNetwork, errors.New("i/o timeout"))
	badCreds := ldap.NewError(ldap.LDAPResultInvalidCredentials, errors.New("x"))

	tests := []struct {
		name string
		prev time.Duration
		err  error
		want time.Duration
	}{
		{"first failure", 0, netErr, sourceBackoffInitial},
		{"doubles", sourceBackoffInitial, netErr, 2 * sourceBackoffInitial},
		{"capped", sourceBackoffMax - time.Second, netErr, sourceBackoffMax},
		{"stays at cap", sourceBackoffMax, netErr, sourceBackoffMax},
		{"invalid credentials jumps to cap", 0, badCreds, sourceBackoffMax},
		{"wrapped invalid credentials", 0, fmt.Errorf("bind: %w", badCreds), sourceBackoffMax},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := nextSourceBackoff(tt.prev, tt.err); got != tt.want {
				t.Errorf("nextSourceBackoff(%s, %v) = %s, want %s", tt.prev, tt.err, got, tt.want)
			}
		})
	}
}

// fakeLDAPServer answers every bind and search with success and counts binds.
func fakeLDAPServer(t *testing.T) (string, *atomic.Int32) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })

	var binds atomic.Int32
	reply := func(c net.Conn, id int64, tag ber.Tag, desc string) {
		op := ber.Encode(ber.ClassApplication, ber.TypeConstructed, tag, nil, desc)
		op.AppendChild(ber.NewInteger(ber.ClassUniversal, ber.TypePrimitive, ber.TagEnumerated, 0, "resultCode"))
		op.AppendChild(ber.NewString(ber.ClassUniversal, ber.TypePrimitive, ber.TagOctetString, "", "matchedDN"))
		op.AppendChild(ber.NewString(ber.ClassUniversal, ber.TypePrimitive, ber.TagOctetString, "", "diagnosticMessage"))
		msg := ber.Encode(ber.ClassUniversal, ber.TypeConstructed, ber.TagSequence, nil, "LDAP Response")
		msg.AppendChild(ber.NewInteger(ber.ClassUniversal, ber.TypePrimitive, ber.TagInteger, id, "MessageID"))
		msg.AppendChild(op)
		c.Write(msg.Bytes())
	}
	serve := func(c net.Conn) {
		defer c.Close()
		var mu sync.Mutex
		for {
			p, err := ber.ReadPacket(c)
			if err != nil || len(p.Children) < 2 {
				return
			}
			id, _ := p.Children[0].Value.(int64)
			mu.Lock()
			switch p.Children[1].Tag {
			case ldap.ApplicationBindRequest:
				binds.Add(1)
				reply(c, id, ldap.ApplicationBindResponse, "Bind Response")
			case ldap.ApplicationSearchRequest:
				reply(c, id, ldap.ApplicationSearchResultDone, "Search Result Done")
			}
			mu.Unlock()
		}
	}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go serve(c)
		}
	}()
	return "ldap://" + ln.Addr().String(), &binds
}

// Many searches polling concurrently must share a single bind.
func TestSearchSource_ConcurrentSearchesShareOneBind(t *testing.T) {
	resetSourceConn(t)
	url, binds := fakeLDAPServer(t)
	prev := config.Source
	config.Source.URL = url
	config.Source.BindDN = "cn=svc"
	config.Source.BindPassword = "secret"
	t.Cleanup(func() {
		sourceConnMu.Lock()
		if sourceConn != nil {
			sourceConn.Close()
		}
		sourceConnMu.Unlock()
		config.Source = prev
	})

	var wg sync.WaitGroup
	for g := 0; g < 50; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 20; i++ {
				if _, err := searchSource("dc=unc,dc=edu", fmt.Sprintf("(memberUid=%d)", g)); err != nil {
					t.Errorf("search failed: %v", err)
					return
				}
			}
		}(g)
	}
	wg.Wait()

	if got := binds.Load(); got != 1 {
		t.Errorf("binds for 1000 searches = %d, want 1", got)
	}
}

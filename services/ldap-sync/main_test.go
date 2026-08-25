package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/labstack/echo/v4"
)

// ---------------------------------------------------------------------------
// Test bootstrap
// ---------------------------------------------------------------------------

func TestMain(m *testing.M) {
	// Use error-level logging during tests to keep output quiet.
	h := slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelError})
	logger = slog.New(h)
	os.Exit(m.Run())
}

func TestLoadConfigResolvesLDAPPasswordFiles(t *testing.T) {
	previousConfig := config
	t.Cleanup(func() { config = previousConfig })

	dir := t.TempDir()
	sourcePasswordFile := dir + "/source-password"
	targetPasswordFile := dir + "/target-password"
	if err := os.WriteFile(sourcePasswordFile, []byte("source-secret\n"), 0600); err != nil {
		t.Fatalf("write source password: %v", err)
	}
	if err := os.WriteFile(targetPasswordFile, []byte(" target-secret \n"), 0600); err != nil {
		t.Fatalf("write target password: %v", err)
	}

	configPath := dir + "/config.yaml"
	configData := "source:\n  bind_password: inline-source\n  bind_password_file: " + sourcePasswordFile + "\ntarget:\n  bind_password_file: " + targetPasswordFile + "\n"
	if err := os.WriteFile(configPath, []byte(configData), 0600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	if err := loadConfig(configPath); err != nil {
		t.Fatalf("loadConfig: %v", err)
	}
	if config.Source.BindPassword != "source-secret" {
		t.Fatalf("source password = %q, want file contents", config.Source.BindPassword)
	}
	if config.Target.BindPassword != "target-secret" {
		t.Fatalf("target password = %q, want trimmed file contents", config.Target.BindPassword)
	}
}

// resetState wipes all package-level mutable state so tests don't bleed into
// each other. Call at the start of any test that touches global maps.
func resetState(t *testing.T) {
	t.Helper()
	searchesMu.Lock()
	searches = make(map[string]*SearchSpec)
	searchesMu.Unlock()

	searchResultsMu.Lock()
	searchResults = make(map[string]map[string]LDAPResult)
	searchResultsMu.Unlock()

	bindingsMu.Lock()
	bindings = make(map[string]string)
	nullBindings = make(map[string]struct{})
	bindingsMu.Unlock()

	dependencyTracker = newDependencyState()
	dnLocks = sync.Map{}
	db = nil

	pluginRegistry = nil
	dispatchSyncEvent = func(event SyncEvent) {
		if pluginRegistry == nil {
			return
		}
		pluginRegistry.Dispatch(event)
	}
}

// mockStore captures calls to ldapStore and records the entries written.
// The reported SyncOp is Created the first time a DN is seen and Updated
// thereafter, mirroring storeDestinationLDAP's Add-vs-Modify branch.
type mockStore struct {
	mu      sync.Mutex
	written []*TransformedEntry
	seen    map[string]struct{}
	err     error // returned on every call if set
}

func (s *mockStore) store(e *TransformedEntry) (SyncOp, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	// Deep-copy content so concurrent mutations don't corrupt the snapshot.
	copied := make(map[string]interface{}, len(e.Content))
	for k, v := range e.Content {
		copied[k] = v
	}
	s.written = append(s.written, &TransformedEntry{DN: e.DN, Content: copied})
	if s.err != nil {
		return "", s.err
	}
	if s.seen == nil {
		s.seen = make(map[string]struct{})
	}
	key := normalizeDN(e.DN)
	if _, ok := s.seen[key]; ok {
		return SyncOpUpdated, nil
	}
	s.seen[key] = struct{}{}
	return SyncOpCreated, nil
}

func (s *mockStore) entries() []*TransformedEntry {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]*TransformedEntry, len(s.written))
	copy(out, s.written)
	return out
}

// withMockStore replaces ldapStore for the duration of t and restores it
// afterward.  It also ensures ldapStore is never nil (it's nil until main()
// sets it, which tests never call).
func withMockStore(t *testing.T) *mockStore {
	t.Helper()
	ms := &mockStore{}
	ldapStore = ms.store
	t.Cleanup(func() { ldapStore = nil })
	return ms
}

// ---------------------------------------------------------------------------
// normalizeDN
// ---------------------------------------------------------------------------

func TestNormalizeDN(t *testing.T) {
	cases := []struct{ in, want string }{
		{"CN=Alice,DC=example,DC=org", "cn=alice,dc=example,dc=org"},
		{"  uid=bob,ou=users  ", "uid=bob,ou=users"},
		{"", ""},
	}
	for _, tc := range cases {
		if got := normalizeDN(tc.in); got != tc.want {
			t.Errorf("normalizeDN(%q) = %q; want %q", tc.in, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// sortedKeys
// ---------------------------------------------------------------------------

func TestSortedKeys(t *testing.T) {
	if sortedKeys(nil) != nil {
		t.Error("expected nil for nil input")
	}
	got := sortedKeys(map[string]struct{}{"c": {}, "a": {}, "b": {}})
	want := []string{"a", "b", "c"}
	for i, v := range want {
		if got[i] != v {
			t.Errorf("sortedKeys[%d] = %q; want %q", i, got[i], v)
		}
	}
}

// ---------------------------------------------------------------------------
// isMergeAttr
// ---------------------------------------------------------------------------

func TestIsMergeAttr(t *testing.T) {
	cases := []struct {
		attr string
		want bool
	}{
		{"groups", true},
		{"Groups", true}, // case-insensitive
		{"GROUPS", true},
		{"memberuid", true},
		{"MemberUID", true},
		{"cn", false},
		{"member", false},
	}
	for _, tc := range cases {
		if got := isMergeAttr(tc.attr); got != tc.want {
			t.Errorf("isMergeAttr(%q) = %v; want %v", tc.attr, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// isSliceValue
// ---------------------------------------------------------------------------

func TestIsSliceValue(t *testing.T) {
	if !isSliceValue([]interface{}{"a"}) {
		t.Error("[]interface{} should be slice")
	}
	if !isSliceValue([]string{"a"}) {
		t.Error("[]string should be slice")
	}
	if isSliceValue("hello") {
		t.Error("string should not be slice")
	}
	if isSliceValue(42) {
		t.Error("int should not be slice")
	}
	if isSliceValue(nil) {
		t.Error("nil should not be slice")
	}
}

// ---------------------------------------------------------------------------
// toStringSlice
// ---------------------------------------------------------------------------

func TestToStringSlice(t *testing.T) {
	got := toStringSlice([]interface{}{"a", 1, true})
	want := []string{"a", "1", "true"}
	if len(got) != len(want) {
		t.Fatalf("len = %d; want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d] = %q; want %q", i, got[i], want[i])
		}
	}

	if got := toStringSlice(nil); got != nil {
		t.Errorf("nil input: got %v; want nil", got)
	}
	if got := toStringSlice("scalar"); len(got) != 1 || got[0] != "scalar" {
		t.Errorf("scalar input: got %v", got)
	}
}

// ---------------------------------------------------------------------------
// mergeUnique
// ---------------------------------------------------------------------------

func TestMergeUnique(t *testing.T) {
	got := mergeUnique([]string{"a", "b"}, []string{"b", "c"})
	want := []string{"a", "b", "c"}
	if len(got) != len(want) {
		t.Fatalf("len = %d; want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d] = %q; want %q", i, got[i], want[i])
		}
	}

	// Empty existing
	got2 := mergeUnique(nil, []string{"x", "y"})
	if len(got2) != 2 || got2[0] != "x" {
		t.Errorf("empty existing: got %v", got2)
	}
}

// ---------------------------------------------------------------------------
// mergeValue
// ---------------------------------------------------------------------------

func TestMergeValue(t *testing.T) {
	// Slice + slice → merged slice
	res := mergeValue([]interface{}{"a"}, []interface{}{"b"})
	sl, ok := res.([]interface{})
	if !ok || len(sl) != 2 {
		t.Errorf("expected 2-element slice, got %T %v", res, res)
	}

	// Scalar: incoming wins
	res2 := mergeValue("old", "new")
	if res2 != "new" {
		t.Errorf("scalar: expected %q got %v", "new", res2)
	}
}

// ---------------------------------------------------------------------------
// mergeEntryContent
// ---------------------------------------------------------------------------

func TestMergeEntryContent(t *testing.T) {
	existing := map[string]interface{}{"a": "1", "b": []interface{}{"x"}}
	incoming := map[string]interface{}{"b": []interface{}{"y"}, "c": "3"}

	merged := mergeEntryContent(existing, incoming)

	if merged["a"] != "1" {
		t.Errorf("key 'a' should be preserved; got %v", merged["a"])
	}
	if merged["c"] != "3" {
		t.Errorf("key 'c' should be added; got %v", merged["c"])
	}
	// 'b' is a slice on both sides → merged
	sl, _ := merged["b"].([]interface{})
	if len(sl) != 2 {
		t.Errorf("slice 'b' should have 2 elements; got %v", sl)
	}

	// Nil guards
	if mergeEntryContent(nil, incoming) == nil {
		t.Error("nil existing should return incoming")
	}
	if mergeEntryContent(existing, nil) == nil {
		t.Error("nil incoming should return existing")
	}
}

// ---------------------------------------------------------------------------
// bindings helpers
// ---------------------------------------------------------------------------

func TestUpdateAndGetBindings(t *testing.T) {
	resetState(t)

	val := "uid1"
	updateBindings(map[string]*string{"pidUidMap.p1": &val})

	snap, nullSnap := getBindingsSnapshot()
	if snap["pidUidMap.p1"] != "uid1" {
		t.Errorf("expected uid1; got %q", snap["pidUidMap.p1"])
	}
	if len(nullSnap) != 0 {
		t.Errorf("expected no null bindings; got %v", nullSnap)
	}

	// Null binding
	updateBindings(map[string]*string{"pidUidMap.p1": nil})
	snap2, nullSnap2 := getBindingsSnapshot()
	if _, ok := snap2["pidUidMap.p1"]; ok {
		t.Error("binding should have been removed")
	}
	if _, ok := nullSnap2["pidUidMap.p1"]; !ok {
		t.Error("null binding should be recorded")
	}
}

// ---------------------------------------------------------------------------
// resolveString
// ---------------------------------------------------------------------------

func TestResolveString(t *testing.T) {
	bind := map[string]string{"foo": "bar"}
	null := map[string]struct{}{}

	// No variables
	got, miss, hasNull := resolveString("hello world", bind, null)
	if got != "hello world" || miss || hasNull {
		t.Errorf("no-var: got (%q, %v, %v)", got, miss, hasNull)
	}

	// Present variable
	got, miss, hasNull = resolveString("$foo", bind, null)
	if got != "bar" || miss || hasNull {
		t.Errorf("present var: got (%q, %v, %v)", got, miss, hasNull)
	}

	// Missing variable
	got, miss, _ = resolveString("$missing", bind, null)
	if !miss {
		t.Error("expected missing=true for unknown variable")
	}
	if got != "$missing" {
		t.Errorf("missing var should be kept verbatim; got %q", got)
	}

	// Null variable
	nullBind := map[string]struct{}{"nullkey": {}}
	got, miss, hasNull = resolveString("$nullkey", bind, nullBind)
	if !hasNull {
		t.Error("expected hasNull=true")
	}
	_ = got
	_ = miss
}

// ---------------------------------------------------------------------------
// resolveEntryTemplates
// ---------------------------------------------------------------------------

func TestResolveEntryTemplates(t *testing.T) {
	resetState(t)
	uid := "alice"
	updateBindings(map[string]*string{"pidUidMap.p1": &uid})
	snap, nullSnap := getBindingsSnapshot()

	entry := &TransformedEntry{
		DN: "uid=$pidUidMap.p1,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{
			"groups": []interface{}{"$pidUidMap.p1"},
		},
	}
	resolved, missing := resolveEntryTemplates(entry, snap, nullSnap)
	if missing {
		t.Error("expected no missing bindings")
	}
	if resolved.DN != "uid=alice,ou=users,dc=example,dc=org" {
		t.Errorf("DN not resolved: %q", resolved.DN)
	}
}

// ---------------------------------------------------------------------------
// collectMissingBindings
// ---------------------------------------------------------------------------

func TestCollectMissingBindings(t *testing.T) {
	bind := map[string]string{"known": "val"}
	null := map[string]struct{}{}

	entry := &TransformedEntry{
		DN:      "$unknown1",
		Content: map[string]interface{}{"attr": "$unknown2"},
	}
	missing := collectMissingBindings(entry, []string{"$unknown3"}, bind, null)
	found := make(map[string]bool)
	for _, k := range missing {
		found[k] = true
	}
	for _, key := range []string{"unknown1", "unknown2", "unknown3"} {
		if !found[key] {
			t.Errorf("missing key %q not reported", key)
		}
	}
}

// ---------------------------------------------------------------------------
// dependencyState — direct write (no deps)
// ---------------------------------------------------------------------------

func TestHandleEntry_NoDeps(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()
	entry := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"users"}},
	}
	ds.handleEntry(entry, nil, "test-search")

	written := ms.entries()
	if len(written) != 1 {
		t.Fatalf("expected 1 write; got %d", len(written))
	}
	if written[0].DN != entry.DN {
		t.Errorf("wrong DN written: %q", written[0].DN)
	}
}

// ---------------------------------------------------------------------------
// dependencyState — pending on unsynced dep
// ---------------------------------------------------------------------------

func TestHandleEntry_PendingDeps(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()
	dep := "uid=bob,ou=users,dc=example,dc=org"
	entry := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"users"}},
	}
	ds.handleEntry(entry, []string{dep}, "test-search")

	// Not written yet — dep not synced
	if len(ms.entries()) != 0 {
		t.Error("entry should be pending, not written yet")
	}

	// Syncing the dep should release alice
	ds.markSyncedAndRelease(dep, "", nil, "")

	written := ms.entries()
	if len(written) != 1 {
		t.Fatalf("expected 1 write after dep synced; got %d", len(written))
	}
}

// ---------------------------------------------------------------------------
// dependencyState — self-dep is ignored (entry goes direct)
// ---------------------------------------------------------------------------

func TestHandleEntry_SelfDepSkipped(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()
	dn := "uid=alice,ou=users,dc=example,dc=org"
	entry := &TransformedEntry{
		DN:      dn,
		Content: map[string]interface{}{"groups": []interface{}{"users"}},
	}
	// dep is same as the entry DN — should be ignored
	ds.handleEntry(entry, []string{dn}, "test-search")

	if len(ms.entries()) != 1 {
		t.Fatalf("self-dep should be skipped; expected 1 write, got %d", len(ms.entries()))
	}
}

// ---------------------------------------------------------------------------
// dependencyState — missing bindings defer entry
// ---------------------------------------------------------------------------

func TestHandleEntry_MissingBindings(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	// Use the global dependencyTracker because updateBindings calls
	// dependencyTracker.reprocessPending() — not a local instance.
	entry := &TransformedEntry{
		DN:      "uid=$pidUidMap.p99,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"users"}},
	}
	dependencyTracker.handleEntry(entry, nil, "test-search")

	// Binding not set → should not be written yet
	if len(ms.entries()) != 0 {
		t.Error("entry with unresolved binding should be pending, not written")
	}

	// Providing the binding triggers reprocessPending synchronously inside
	// updateBindings → handleEntry.
	uid := "alice"
	updateBindings(map[string]*string{"pidUidMap.p99": &uid})

	written := ms.entries()
	if len(written) != 1 {
		t.Fatalf("after binding set expected 1 write; got %d", len(written))
	}
}

// ---------------------------------------------------------------------------
// dependencyState — concurrent handleEntry for same DN must merge (race fix)
// ---------------------------------------------------------------------------

func TestHandleEntry_ConcurrentSameDN_MergesGroups(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()

	// Use a shared dep that isn't synced yet, forcing both patches into pending.
	sharedDep := "uid=other,ou=users,dc=example,dc=org"

	// Eagle and Falcon group patches both target Alice and list sharedDep.
	eaglePatch := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"eagle"}},
	}
	falconPatch := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"falcon"}},
	}

	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); ds.handleEntry(eaglePatch, []string{sharedDep}, "test-search") }()
	go func() { defer wg.Done(); ds.handleEntry(falconPatch, []string{sharedDep}, "test-search") }()
	wg.Wait()

	// Both patches pending — nothing written yet
	if len(ms.entries()) != 0 {
		t.Fatalf("expected 0 writes before dep synced; got %d", len(ms.entries()))
	}

	// Release the shared dep → pending entry for Alice fires
	ds.markSyncedAndRelease(sharedDep, "", nil, "")

	written := ms.entries()
	if len(written) != 1 {
		t.Fatalf("expected exactly 1 write for Alice; got %d", len(written))
	}

	// The written entry must contain BOTH group values.
	groups, ok := written[0].Content["groups"]
	if !ok {
		t.Fatal("groups attribute missing from written entry")
	}
	var vals []string
	switch v := groups.(type) {
	case []interface{}:
		for _, x := range v {
			vals = append(vals, x.(string))
		}
	case []string:
		vals = v
	default:
		t.Fatalf("unexpected groups type %T", groups)
	}
	hasEagle, hasFalcon := false, false
	for _, g := range vals {
		if g == "eagle" {
			hasEagle = true
		}
		if g == "falcon" {
			hasFalcon = true
		}
	}
	if !hasEagle || !hasFalcon {
		t.Errorf("expected both groups in entry; got %v", vals)
	}
}

// ---------------------------------------------------------------------------
// dependencyState — deterministic race reproduction
//
// TestHandleEntry_DeterministicRace uses handleEntryWindowHook to hold both
// goroutines inside the two-phase lock window simultaneously, guaranteeing the
// exact interleaving that caused groups to be dropped before the fix.
//
// Without the fix (the conflicting-pending merge block in the second lock
// section), this test reliably fails: only one group value survives.
// With the fix it always passes.
// ---------------------------------------------------------------------------

func TestHandleEntry_DeterministicRace(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()
	sharedDep := "uid=other,ou=users,dc=example,dc=org"

	eaglePatch := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"eagle"}},
	}
	falconPatch := &TransformedEntry{
		DN:      "uid=alice,ou=users,dc=example,dc=org",
		Content: map[string]interface{}{"groups": []interface{}{"falcon"}},
	}

	// Barrier: block each goroutine in the race window until BOTH have arrived,
	// then release them simultaneously.  This deterministically recreates the
	// interleaving where both goroutines complete phase-1 (find no pending entry)
	// before either starts phase-2 (write to pending).
	var arrivals atomic.Int32
	allArrived := make(chan struct{})
	release := make(chan struct{})

	handleEntryWindowHook = func() {
		if arrivals.Add(1) == 2 {
			close(allArrived) // last goroutine signals the barrier is full
		}
		<-release // both goroutines stall here until the test releases them
	}
	t.Cleanup(func() { handleEntryWindowHook = nil })

	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); ds.handleEntry(eaglePatch, []string{sharedDep}, "test-search") }()
	go func() { defer wg.Done(); ds.handleEntry(falconPatch, []string{sharedDep}, "test-search") }()

	// Wait until both goroutines are stalled inside the window (up to 5 s).
	select {
	case <-allArrived:
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for both goroutines to enter the race window")
	}

	// Both are now past phase-1 (found no pending entry for Alice) but have not
	// yet reached phase-2 (the second d.mu.Lock).  Release them both at once.
	close(release)
	wg.Wait()

	// Neither should be written yet — both are pending on sharedDep.
	if n := len(ms.entries()); n != 0 {
		t.Fatalf("expected 0 writes before dep synced; got %d", n)
	}

	ds.markSyncedAndRelease(sharedDep, "", nil, "")

	written := ms.entries()
	if len(written) != 1 {
		t.Fatalf("expected exactly 1 write for Alice; got %d", len(written))
	}

	got := groupSlice(t, written[0])
	if !sliceContains(got, "eagle") || !sliceContains(got, "falcon") {
		t.Errorf("both group values must survive the race; got %v", got)
	}
}

// groupSlice extracts the groups attribute from a TransformedEntry as []string.
func groupSlice(t *testing.T, e *TransformedEntry) []string {
	t.Helper()
	switch v := e.Content["groups"].(type) {
	case []interface{}:
		out := make([]string, len(v))
		for i, x := range v {
			out[i] = fmt.Sprintf("%v", x)
		}
		return out
	case []string:
		return v
	default:
		t.Fatalf("unexpected groups type %T", e.Content["groups"])
		return nil
	}
}

// sliceContains reports whether s appears in ss.
func sliceContains(ss []string, s string) bool {
	for _, v := range ss {
		if v == s {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// dependencyState — markSyncedAndRelease chains
// ---------------------------------------------------------------------------

func TestMarkSyncedAndRelease_Chain(t *testing.T) {
	resetState(t)
	ms := withMockStore(t)

	ds := newDependencyState()

	// C depends on B, B depends on A.
	entryA := &TransformedEntry{DN: "uid=a,ou=users,dc=example,dc=org", Content: map[string]interface{}{}}
	entryB := &TransformedEntry{DN: "uid=b,ou=users,dc=example,dc=org", Content: map[string]interface{}{}}
	entryC := &TransformedEntry{DN: "uid=c,ou=users,dc=example,dc=org", Content: map[string]interface{}{}}

	ds.handleEntry(entryC, []string{entryB.DN}, "test-search")
	ds.handleEntry(entryB, []string{entryA.DN}, "test-search")
	// A has no deps → written immediately
	ds.handleEntry(entryA, nil, "test-search")

	written := ms.entries()
	if len(written) != 3 {
		t.Fatalf("expected 3 writes (A, B, C in order); got %d: %v", len(written), written)
	}
	if written[0].DN != entryA.DN {
		t.Errorf("first write should be A; got %q", written[0].DN)
	}
}

// ---------------------------------------------------------------------------
// HTTP handler helpers
// ---------------------------------------------------------------------------

func echoContext(method, path string, form url.Values) (echo.Context, *httptest.ResponseRecorder) {
	req := httptest.NewRequest(method, path, strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	return c, rec
}

// ---------------------------------------------------------------------------
// createSearchHandler
// ---------------------------------------------------------------------------

func TestCreateSearchHandler_Basic(t *testing.T) {
	resetState(t)
	form := url.Values{"id": {"s1"}, "filter": {"(objectClass=*)"}, "refresh": {"30"}}
	c, rec := echoContext(http.MethodPost, "/search", form)

	if err := createSearchHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}

	searchesMu.RLock()
	_, ok := searches["s1"]
	searchesMu.RUnlock()
	if !ok {
		t.Error("search not registered after create")
	}

	// Clean up the goroutine started by the handler
	searchesMu.RLock()
	spec := searches["s1"]
	searchesMu.RUnlock()
	close(spec.Stop)
}

func TestCreateSearchHandler_MissingParams(t *testing.T) {
	resetState(t)
	form := url.Values{"id": {"s1"}} // missing filter and refresh
	c, rec := echoContext(http.MethodPost, "/search", form)
	_ = createSearchHandler(c)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d; want 400", rec.Code)
	}
}

func TestCreateSearchHandler_Duplicate(t *testing.T) {
	resetState(t)

	// Pre-populate the map
	stopChan := make(chan struct{})
	searchesMu.Lock()
	searches["dup"] = &SearchSpec{Filter: "(cn=*)", Refresh: 10, Stop: stopChan}
	searchesMu.Unlock()
	defer close(stopChan)

	form := url.Values{"id": {"dup"}, "filter": {"(cn=*)"}, "refresh": {"10"}}
	c, rec := echoContext(http.MethodPost, "/search", form)
	_ = createSearchHandler(c)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d; want 400", rec.Code)
	}
}

// TestCreateSearchHandler_ConcurrentDuplicate verifies the TOCTOU fix: two
// simultaneous creates for the same id must result in exactly one success.
func TestCreateSearchHandler_ConcurrentDuplicate(t *testing.T) {
	resetState(t)

	var (
		ok400 int
		ok200 int
		mu    sync.Mutex
		wg    sync.WaitGroup
	)

	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			form := url.Values{"id": {"race-id"}, "filter": {"(cn=*)"}, "refresh": {"5"}, "oneShot": {"true"}}
			c, rec := echoContext(http.MethodPost, "/search", form)
			_ = createSearchHandler(c)
			mu.Lock()
			if rec.Code == http.StatusOK {
				ok200++
			} else {
				ok400++
			}
			mu.Unlock()
		}()
	}
	wg.Wait()

	if ok200 != 1 {
		t.Errorf("expected exactly 1 successful create; got %d", ok200)
	}

	// Clean up goroutine
	searchesMu.RLock()
	spec, exists := searches["race-id"]
	searchesMu.RUnlock()
	if exists {
		close(spec.Stop)
	}
}

// ---------------------------------------------------------------------------
// getSearchHandler
// ---------------------------------------------------------------------------

func TestGetSearchHandler_All(t *testing.T) {
	resetState(t)
	stop := make(chan struct{})
	searchesMu.Lock()
	searches["q1"] = &SearchSpec{Filter: "(cn=*)", Refresh: 10, Stop: stop}
	searchesMu.Unlock()
	defer close(stop)

	req := httptest.NewRequest(http.MethodGet, "/search", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)

	if err := getSearchHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
	var results []SearchInfo
	if err := json.Unmarshal(rec.Body.Bytes(), &results); err != nil {
		t.Fatal(err)
	}
	if len(results) != 1 || results[0].ID != "q1" {
		t.Errorf("unexpected results: %+v", results)
	}
}

func TestGetSearchHandler_ByID(t *testing.T) {
	resetState(t)
	stop := make(chan struct{})
	searchesMu.Lock()
	searches["q2"] = &SearchSpec{Filter: "(uid=*)", Refresh: 20, Stop: stop}
	searchesMu.Unlock()
	defer close(stop)

	req := httptest.NewRequest(http.MethodGet, "/search?id=q2", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.QueryParams().Set("id", "q2")

	if err := getSearchHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
	var info SearchInfo
	if err := json.Unmarshal(rec.Body.Bytes(), &info); err != nil {
		t.Fatal(err)
	}
	if info.ID != "q2" || info.Filter != "(uid=*)" {
		t.Errorf("unexpected info: %+v", info)
	}
}

func TestGetSearchHandler_NotFound(t *testing.T) {
	resetState(t)
	req := httptest.NewRequest(http.MethodGet, "/search?id=nope", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.QueryParams().Set("id", "nope")

	_ = getSearchHandler(c)
	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d; want 404", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// deleteSearchHandler
// ---------------------------------------------------------------------------

func TestDeleteSearchHandler_Basic(t *testing.T) {
	resetState(t)
	stop := make(chan struct{})
	searchesMu.Lock()
	searches["del1"] = &SearchSpec{Filter: "(cn=*)", Refresh: 10, Stop: stop}
	searchesMu.Unlock()
	searchResultsMu.Lock()
	searchResults["del1"] = make(map[string]LDAPResult)
	searchResultsMu.Unlock()

	req := httptest.NewRequest(http.MethodDelete, "/search/del1", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("del1")

	if err := deleteSearchHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
	searchesMu.RLock()
	_, exists := searches["del1"]
	searchesMu.RUnlock()
	if exists {
		t.Error("search should be removed after delete")
	}
}

func TestDeleteSearchHandler_NotFound(t *testing.T) {
	resetState(t)
	req := httptest.NewRequest(http.MethodDelete, "/search/ghost", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("ghost")

	_ = deleteSearchHandler(c)
	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d; want 404", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// updateSearchHandler
// ---------------------------------------------------------------------------

func TestUpdateSearchHandler_Basic(t *testing.T) {
	resetState(t)
	stop := make(chan struct{})
	searchesMu.Lock()
	searches["upd1"] = &SearchSpec{Filter: "(cn=*)", Refresh: 10, Stop: stop}
	searchesMu.Unlock()

	form := url.Values{"filter": {"(uid=*)"}, "refresh": {"60"}, "oneShot": {"true"}}
	req := httptest.NewRequest(http.MethodPut, "/search/upd1", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("upd1")

	if err := updateSearchHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
	searchesMu.RLock()
	spec := searches["upd1"]
	searchesMu.RUnlock()
	close(spec.Stop)
}

func TestUpdateSearchHandler_NotFound(t *testing.T) {
	resetState(t)
	form := url.Values{"filter": {"(uid=*)"}, "refresh": {"60"}}
	req := httptest.NewRequest(http.MethodPut, "/search/missing", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("missing")

	_ = updateSearchHandler(c)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d; want 400", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// getResultsHandler
// ---------------------------------------------------------------------------

func TestGetResultsHandler_Simple(t *testing.T) {
	resetState(t)
	searchResultsMu.Lock()
	searchResults["r1"] = map[string]LDAPResult{
		"uid=alice,ou=users,dc=example,dc=org": {
			DN:      "uid=alice,ou=users,dc=example,dc=org",
			Content: map[string]interface{}{"cn": "Alice"},
		},
	}
	searchResultsMu.Unlock()

	req := httptest.NewRequest(http.MethodGet, "/results/r1", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("r1")

	if err := getResultsHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
	var results []ResultEntrySimple
	if err := json.Unmarshal(rec.Body.Bytes(), &results); err != nil {
		t.Fatal(err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result; got %d", len(results))
	}
}

func TestGetResultsHandler_Full(t *testing.T) {
	resetState(t)
	searchResultsMu.Lock()
	searchResults["r2"] = map[string]LDAPResult{
		"uid=bob,ou=users,dc=example,dc=org": {
			DN:      "uid=bob,ou=users,dc=example,dc=org",
			Content: map[string]interface{}{"cn": "Bob"},
		},
	}
	searchResultsMu.Unlock()

	req := httptest.NewRequest(http.MethodGet, "/results/r2?full=true", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("r2")
	c.QueryParams().Set("full", "true")

	if err := getResultsHandler(c); err != nil {
		t.Fatal(err)
	}
	var results []ResultEntryFull
	if err := json.Unmarshal(rec.Body.Bytes(), &results); err != nil {
		t.Fatal(err)
	}
	if len(results) != 1 || results[0].Content["cn"] != "Bob" {
		t.Errorf("unexpected results: %+v", results)
	}
}

func TestGetResultsHandler_NotFound(t *testing.T) {
	resetState(t)
	req := httptest.NewRequest(http.MethodGet, "/results/nope", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	c.SetParamNames("id")
	c.SetParamValues("nope")

	_ = getResultsHandler(c)
	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d; want 404", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// logLevelHandler
// ---------------------------------------------------------------------------

func TestLogLevelHandler_Valid(t *testing.T) {
	for _, level := range []string{"debug", "info", "warn", "error"} {
		body := `{"level":"` + level + `"}`
		req := httptest.NewRequest(http.MethodPut, "/loglevel", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		e := echo.New()
		c := e.NewContext(req, rec)

		if err := logLevelHandler(c); err != nil {
			t.Fatalf("level %q: %v", level, err)
		}
		if rec.Code != http.StatusOK {
			t.Errorf("level %q: status = %d; want 200", level, rec.Code)
		}
	}
}

func TestLogLevelHandler_Invalid(t *testing.T) {
	req := httptest.NewRequest(http.MethodPut, "/loglevel", strings.NewReader(`{"level":"trace"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)

	_ = logLevelHandler(c)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d; want 400", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// probe handlers
// ---------------------------------------------------------------------------

func TestHealthzHandler(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)

	if err := healthzHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
}

func TestReadyzHandler(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)

	if err := readyzHandler(c); err != nil {
		t.Fatal(err)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d; want 200", rec.Code)
	}
}

package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/labstack/echo/v4"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func resetHookState() {
	pidUidMap = make(map[string]string)
	baseGid = "200"
	baseGroup = "users"
}

func postHook(t *testing.T, body string) (int, HookResponse) {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/hook", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)

	if err := hookHandler(c); err != nil {
		t.Fatalf("hookHandler error: %v", err)
	}
	var resp HookResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return rec.Code, resp
}

// ---------------------------------------------------------------------------
// extractCN
// ---------------------------------------------------------------------------

func TestExtractCN(t *testing.T) {
	cases := []struct{ dn, want string }{
		{"cn=users,ou=groups,dc=example,dc=org", "users"},
		{"cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu", "unc:app:renci:eagle"},
		{"uid=alice,ou=users", ""},
		{"", ""},
	}
	for _, tc := range cases {
		if got := extractCN(tc.dn); got != tc.want {
			t.Errorf("extractCN(%q) = %q; want %q", tc.dn, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// extractGroupName
// ---------------------------------------------------------------------------

func TestExtractGroupName(t *testing.T) {
	// ordrd-group-x extractGroupName requires the "cn=unc:app:renci:" prefix;
	// DNs without it return "".
	cases := []struct{ dn, want string }{
		{"cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu", "eagle"},
		{"cn=unc:app:renci:users,ou=Groups,dc=unc,dc=edu", "users"},
		{"cn=plaingroup,ou=Groups,dc=unc,dc=edu", ""},   // no prefix → ""
		{"uid=alice,ou=users", ""},
		{"cn=unc:app:renci:,ou=groups", ""}, // empty suffix after prefix
	}
	for _, tc := range cases {
		if got := extractGroupName(tc.dn); got != tc.want {
			t.Errorf("extractGroupName(%q) = %q; want %q", tc.dn, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// copyMap
// ---------------------------------------------------------------------------

func TestCopyMap(t *testing.T) {
	orig := map[string]interface{}{"a": "1", "b": []string{"x"}}
	copied := copyMap(orig)
	copied["a"] = "99"
	if orig["a"] != "1" {
		t.Error("copyMap should not mutate original")
	}
}

// ---------------------------------------------------------------------------
// processUNCUser
// ---------------------------------------------------------------------------

func TestProcessUNCUser_Basic(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN: "pid=p1,ou=people,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"uid":       "alice",
			"pid":       "p1",
			"cn":        "Alice Smith",
			"sn":        "Smith",
			"givenName": "Alice",
			"uidNumber": "1001",
		},
	}
	resp := processUNCUser(req)

	// User entry only (ordrd version has no base group entry in transformed)
	if len(resp.Transformed) != 1 {
		t.Fatalf("expected 1 transformed entry; got %d", len(resp.Transformed))
	}
	entry := resp.Transformed[0]
	dn, _ := entry["dn"].(string)
	if dn != "uid=alice,ou=users,dc=example,dc=org" {
		t.Errorf("DN = %q; want uid=alice,...", dn)
	}
	content, _ := entry["content"].(map[string]interface{})
	groups, _ := content["groups"].([]interface{})
	if len(groups) == 0 || groups[0] != "users" {
		t.Errorf("groups should contain base group; got %v", groups)
	}

	// pidUidMap updated
	if pidUidMap["p1"] != "alice" {
		t.Errorf("pidUidMap[p1] = %q; want alice", pidUidMap["p1"])
	}
}

func TestProcessUNCUser_MissingUID(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN:      "pid=p2,ou=people,dc=unc,dc=edu",
		Content: map[string]interface{}{"pid": "p2"},
	}
	resp := processUNCUser(req)
	if resp.Transformed != nil {
		t.Error("expected nil transformed for missing uid")
	}
	if resp.Reset != true {
		t.Error("expected reset=true when uid missing")
	}
}

// ---------------------------------------------------------------------------
// processORDRDGroup
// ---------------------------------------------------------------------------

func TestProcessORDRDGroup_NoMapping(t *testing.T) {
	resetHookState()
	// p1 has no entry in pidUidMap — mapping missing
	req := HookRequest{
		DN: "cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"member": []interface{}{"pid=p1,ou=people,dc=unc,dc=edu"},
		},
	}
	resp := processORDRDGroup(req)
	if resp.Transformed != nil {
		t.Error("expected nil transformed when pid mapping is missing")
	}
	if !resp.Reset {
		t.Error("expected reset=true when mapping is missing")
	}
}

func TestProcessORDRDGroup_WithMapping(t *testing.T) {
	resetHookState()
	pidUidMap["p1"] = "alice"
	pidUidMap["p2"] = "bob"

	req := HookRequest{
		DN: "cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"member": []interface{}{
				"pid=p1,ou=people,dc=unc,dc=edu",
				"pid=p2,ou=people,dc=unc,dc=edu",
			},
		},
	}
	resp := processORDRDGroup(req)

	// group entry + 2 user-group patches
	if len(resp.Transformed) != 3 {
		t.Fatalf("expected 3 transformed entries; got %d", len(resp.Transformed))
	}
	groupEntry := resp.Transformed[0]
	dn, _ := groupEntry["dn"].(string)
	if dn != "cn=eagle,ou=groups,dc=example,dc=org" {
		t.Errorf("group DN = %q", dn)
	}

	// Verify user-group patches carry the groupname
	for i, patch := range resp.Transformed[1:] {
		content, _ := patch["content"].(map[string]interface{})
		groups, _ := content["groups"].([]interface{})
		if len(groups) == 0 || groups[0] != "eagle" {
			t.Errorf("patch[%d] groups = %v; want [eagle]", i, groups)
		}
	}
}

func TestProcessORDRDGroup_NoMember(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN:      "cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu",
		Content: map[string]interface{}{},
	}
	resp := processORDRDGroup(req)
	if resp.Transformed != nil {
		t.Error("expected nil transformed when member field missing")
	}
	if !resp.Reset {
		t.Error("expected reset=true when member missing")
	}
}

// ---------------------------------------------------------------------------
// processPosixGroup
// ---------------------------------------------------------------------------

func TestProcessPosixGroup_Basic(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN: "cn=staff,ou=PosixGroups,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"cn":          "staff",
			"gidNumber":   "500",
			"objectClass": []interface{}{"top", "posixGroup", "UNCGroup"},
		},
	}
	resp := processPosixGroup(req)

	if len(resp.Transformed) != 1 {
		t.Fatalf("expected 1 transformed entry; got %d", len(resp.Transformed))
	}
	entry := resp.Transformed[0]
	dn, _ := entry["dn"].(string)
	if dn != "cn=staff,ou=groups,dc=example,dc=org" {
		t.Errorf("DN = %q; want cn=staff,ou=groups,dc=example,dc=org", dn)
	}
	content, _ := entry["content"].(map[string]interface{})
	oc, _ := content["objectClass"].([]string)
	for _, c := range oc {
		if c == "UNCGroup" {
			t.Error("UNCGroup objectClass should be stripped")
		}
	}
}

func TestProcessPosixGroup_WithMemberUID(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN: "cn=eng,ou=PosixGroups,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"cn":        "eng",
			"memberuid": []interface{}{"alice", "bob"},
		},
	}
	resp := processPosixGroup(req)
	entry := resp.Transformed[0]
	content, _ := entry["content"].(map[string]interface{})
	if _, present := content["memberuid"]; present {
		t.Error("memberuid should be removed from content")
	}
	if entry["memberuid"] == nil {
		t.Error("memberuid should be promoted to top-level")
	}
}

// ---------------------------------------------------------------------------
// hookHandler — full HTTP round-trip
// ---------------------------------------------------------------------------

func TestHookHandler_UNCUser(t *testing.T) {
	resetHookState()
	body := `{"dn":"pid=p9,ou=people,dc=unc,dc=edu","content":{"uid":"dave","pid":"p9","cn":"Dave","sn":"D","givenName":"Dave","uidNumber":"1009"}}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if len(resp.Transformed) == 0 {
		t.Error("expected transformed entries")
	}
}

func TestHookHandler_ORDRDGroup_MissingMapping(t *testing.T) {
	resetHookState()
	body := `{"dn":"cn=unc:app:renci:falcon,ou=Groups,dc=unc,dc=edu","content":{"member":["pid=p99,ou=people,dc=unc,dc=edu"]}}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if !resp.Reset {
		t.Error("expected reset=true for missing pid mapping")
	}
}

func TestHookHandler_PosixGroup(t *testing.T) {
	resetHookState()
	body := `{"dn":"cn=ops,ou=PosixGroups,dc=unc,dc=edu","content":{"cn":"ops","objectClass":["top","posixGroup"]}}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if len(resp.Transformed) != 1 {
		t.Errorf("expected 1 transformed; got %d", len(resp.Transformed))
	}
}

func TestHookHandler_Unknown(t *testing.T) {
	resetHookState()
	body := `{"dn":"ou=unknown,dc=example,dc=org","content":{}}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if resp.Transformed != nil {
		t.Errorf("expected nil transformed for unknown DN; got %v", resp.Transformed)
	}
}

func TestHookHandler_BadJSON(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/hook", strings.NewReader("not json"))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e := echo.New()
	c := e.NewContext(req, rec)
	_ = hookHandler(c)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d; want 400", rec.Code)
	}
}

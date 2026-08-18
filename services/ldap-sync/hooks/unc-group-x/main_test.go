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
	cases := []struct{ dn, want string }{
		{"cn=unc:app:renci:eagle,ou=Groups,dc=unc,dc=edu", "eagle"},
		{"cn=unc:app:renci:users,ou=Groups,dc=unc,dc=edu", "users"},
		{"cn=plaingroup,ou=Groups,dc=unc,dc=edu", "plaingroup"},
		{"uid=alice,ou=users", ""},     // no cn= prefix → empty
		{"cn=,ou=groups", ""},          // empty cn value
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
	orig := map[string]interface{}{"a": "1", "b": []string{"x", "y"}}
	copied := copyMap(orig)

	if copied["a"] != "1" {
		t.Error("scalar value not copied")
	}
	// Mutations to copy must not affect original
	copied["a"] = "99"
	if orig["a"] != "1" {
		t.Error("copyMap is not a shallow copy — mutated original")
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

	if len(resp.Transformed) != 2 {
		// user entry + base group entry
		t.Fatalf("expected 2 transformed entries; got %d", len(resp.Transformed))
	}
	userEntry := resp.Transformed[0]
	dn, _ := userEntry["dn"].(string)
	if dn != "uid=alice,ou=users,dc=example,dc=org" {
		t.Errorf("unexpected DN %q", dn)
	}
	content, _ := userEntry["content"].(map[string]interface{})
	if content["uid"] != "alice" {
		t.Errorf("uid not set correctly: %v", content["uid"])
	}
	groups, _ := content["groups"].([]interface{})
	if len(groups) == 0 || groups[0] != "users" {
		t.Errorf("groups should contain base group; got %v", groups)
	}

	// Binding should be published
	if resp.Bindings["pidUidMap.p1"] == nil || *resp.Bindings["pidUidMap.p1"] != "alice" {
		t.Errorf("binding pidUidMap.p1 not set correctly")
	}

	// pidUidMap should be updated
	if pidUidMap["p1"] != "alice" {
		t.Errorf("pidUidMap not updated; got %q", pidUidMap["p1"])
	}
}

func TestProcessUNCUser_MissingUID(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN: "pid=p2,ou=people,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"pid": "p2",
			// uid intentionally absent
		},
	}
	resp := processUNCUser(req)

	if resp.Transformed != nil {
		t.Error("expected nil transformed for missing uid")
	}
	// Null binding should be published for pid
	if val, ok := resp.Bindings["pidUidMap.p2"]; !ok || val != nil {
		t.Errorf("expected null binding for pidUidMap.p2; got %v", val)
	}
}

func TestProcessUNCUser_NoPID(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN:      "pid=p3,ou=people,dc=unc,dc=edu",
		Content: map[string]interface{}{
			// neither uid nor pid
		},
	}
	resp := processUNCUser(req)
	if resp.Transformed != nil {
		t.Error("expected nil transformed for missing uid and pid")
	}
}

// ---------------------------------------------------------------------------
// processORDRDGroup
// ---------------------------------------------------------------------------

func TestProcessORDRDGroup_Basic(t *testing.T) {
	resetHookState()
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
		t.Errorf("group DN = %q; want cn=eagle,ou=groups,dc=example,dc=org", dn)
	}

	// User patches should target template DNs and carry groups=[eagle]
	for i, patch := range resp.Transformed[1:] {
		patchContent, _ := patch["content"].(map[string]interface{})
		g, _ := patchContent["groups"].([]interface{})
		if len(g) == 0 || g[0] != "eagle" {
			t.Errorf("patch[%d] groups = %v; want [eagle]", i, g)
		}
	}

	// dependencies should list the user template DNs
	if len(resp.Dependencies) != 2 {
		t.Errorf("expected 2 dependencies; got %d", len(resp.Dependencies))
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
}

func TestProcessORDRDGroup_BadGroupname(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN:      "uid=something,ou=users,dc=example,dc=org", // not cn=unc:app:renci:
		Content: map[string]interface{}{"member": []interface{}{}},
	}
	resp := processORDRDGroup(req)
	if resp.Transformed != nil {
		t.Error("expected nil transformed for unrecognised DN")
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
			t.Error("UNCGroup objectClass should have been stripped")
		}
	}
}

func TestProcessPosixGroup_WithMemberUID(t *testing.T) {
	resetHookState()
	req := HookRequest{
		DN: "cn=staff,ou=PosixGroups,dc=unc,dc=edu",
		Content: map[string]interface{}{
			"cn":        "staff",
			"memberuid": []interface{}{"alice", "bob"},
		},
	}
	resp := processPosixGroup(req)

	entry := resp.Transformed[0]
	content, _ := entry["content"].(map[string]interface{})
	if _, present := content["memberuid"]; present {
		t.Error("memberuid should have been removed from content")
	}
	if entry["memberuid"] == nil {
		t.Error("memberuid should be promoted to top-level of transformed entry")
	}
}

// ---------------------------------------------------------------------------
// hookHandler — full HTTP round-trip
// ---------------------------------------------------------------------------

func TestHookHandler_UNCUser(t *testing.T) {
	resetHookState()
	body := `{
		"dn": "pid=p5,ou=people,dc=unc,dc=edu",
		"content": {
			"uid": "charlie", "pid": "p5", "cn": "Charlie",
			"sn": "Brown", "givenName": "Charlie", "uidNumber": "1005"
		}
	}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if len(resp.Transformed) == 0 {
		t.Error("expected transformed entries for UNC user")
	}
}

func TestHookHandler_ORDRDGroup(t *testing.T) {
	resetHookState()
	body := `{
		"dn": "cn=unc:app:renci:falcon,ou=Groups,dc=unc,dc=edu",
		"content": {
			"member": ["pid=p1,ou=people,dc=unc,dc=edu"]
		}
	}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if len(resp.Transformed) == 0 {
		t.Error("expected transformed entries for ORDRD group")
	}
}

func TestHookHandler_PosixGroup(t *testing.T) {
	resetHookState()
	body := `{
		"dn": "cn=eng,ou=PosixGroups,dc=unc,dc=edu",
		"content": {"cn": "eng", "gidNumber": "600", "objectClass": ["top","posixGroup"]}
	}`
	code, resp := postHook(t, body)
	if code != http.StatusOK {
		t.Errorf("status = %d; want 200", code)
	}
	if len(resp.Transformed) != 1 {
		t.Errorf("expected 1 transformed entry; got %d", len(resp.Transformed))
	}
}

func TestHookHandler_Unknown(t *testing.T) {
	resetHookState()
	body := `{"dn": "ou=unknown,dc=example,dc=org", "content": {}}`
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

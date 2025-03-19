// main.go
//
// @title ordrd-group-x Hook Service
// @version 1.0
// @description This hook service integrates with the LDAP synchronization
// system to transform LDAP entries and generate additional search specs.
// @host localhost:5001
// @BasePath /
package main

import (
	"log"
	"net/http"
	"strings"

	"github.com/labstack/echo/v4"
)

// Global in-memory map to hold pid->uid mappings.
// In a production system, consider thread-safety (e.g. sync.RWMutex).
var pidUidMap = make(map[string]string)

// HookRequest represents the incoming payload for the hook.
type HookRequest struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// SearchSpec defines a derived LDAP search specification.
type SearchSpec struct {
	ID      string `json:"id"`
	Filter  string `json:"filter"`
	Refresh int    `json:"refresh"`
	BaseDN  string `json:"baseDN"`
}

// Transformed holds the transformed DN and content.
type Transformed struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// HookResponse represents the complete response from the hook.
type HookResponse struct {
	Transformed *Transformed `json:"transformed"` // set to null if transformation fails
	Derived     []SearchSpec `json:"derived"`
	Reset       bool         `json:"reset"`
}

// ErrorResponse represents an error message response.
type ErrorResponse struct {
	Message string `json:"message"`
}

// contains checks if the given value (expected to be a slice or string)
// contains the target string.
func contains(v interface{}, target string) bool {
	switch t := v.(type) {
	case []interface{}:
		for _, item := range t {
			if s, ok := item.(string); ok && s == target {
				return true
			}
		}
	case string:
		return t == target
	}
	return false
}

// extractPID parses a member string to extract the PID value.
// Expected format: "pid=713272486,ou=people,dc=unc,dc=edu"
func extractPID(member string) string {
	const prefix = "pid="
	if strings.HasPrefix(member, prefix) {
		rest := member[len(prefix):]
		parts := strings.Split(rest, ",")
		if len(parts) > 0 {
			return parts[0]
		}
	}
	return ""
}

// processGroup handles the transformation for group (Example1) entries.
// It applies custom transformation logic including mapping pids to uids,
// constructing a new DN and content, and creating derived search specifications.
//
// NOTE: Replace the sample transformation logic below with your own
// if required.
func processGroup(req HookRequest) (*Transformed, []SearchSpec, bool) {
	// Transform the common name.
	cn, _ := req.Content["cn"].(string)
	parts := strings.Split(cn, ":")
	newCN := parts[len(parts)-1]
	newDN := "cn=" + newCN + ",ou=groups,dc=example,dc=org"

	// Process member list and collect pids.
	membersInterface, exists := req.Content["member"]
	var newMembers []string
	var pids []string
	reset := false

	if exists {
		switch m := membersInterface.(type) {
		case []interface{}:
			for _, mem := range m {
				if memStr, ok := mem.(string); ok {
					pid := extractPID(memStr)
					if pid == "" {
						continue
					}
					pids = append(pids, pid)
					uid, found := pidUidMap[pid]
					if !found {
						// If any uid is missing from the pidUidMap, signal a reset.
						reset = true
					} else {
						newMembers = append(newMembers, "uid="+uid+",ou=users,dc=example,dc=org")
					}
				}
			}
		case string:
			pid := extractPID(m)
			if pid != "" {
				pids = append(pids, pid)
				uid, found := pidUidMap[pid]
				if !found {
					reset = true
				} else {
					newMembers = append(newMembers, "uid="+uid+",ou=users,dc=example,dc=org")
				}
			}
		}
	}

	// If any uids were not found, set transformed to null and reset to true.
	var transformed *Transformed
	if reset {
		transformed = nil
	} else {
		newContent := make(map[string]interface{})
		newContent["cn"] = newCN
		newContent["member"] = newMembers
		newContent["objectClass"] = []string{"top", "groupOfNames"}
		transformed = &Transformed{
			DN:      newDN,
			Content: newContent,
		}
	}

	// Build derived search specification.
	var filter string
	if len(pids) > 0 {
		filter = "(|"
		for _, pid := range pids {
			filter += "(pid=" + pid + ")"
		}
		filter += ")"
	}
	derived := []SearchSpec{
		{
			ID:      "ordrd-members",
			Filter:  filter,
			Refresh: 10,
			BaseDN:  "ou=people,dc=unc,dc=edu",
		},
	}

	return transformed, derived, reset
}

// processUser handles the transformation for user (Example2) entries.
// It extracts necessary fields, builds a new DN and content, and
// updates the global pidUidMap.
//
// NOTE: Replace the sample transformation logic below with your own
// if required.
func processUser(req HookRequest) (*Transformed, []SearchSpec, bool) {
	uid, ok := req.Content["uid"].(string)
	if !ok {
		return nil, nil, false
	}
	newDN := "uid=" + uid + ",ou=users,dc=example,dc=org"

	newContent := make(map[string]interface{})
	if v, ok := req.Content["cn"]; ok {
		newContent["cn"] = v
	}
	if v, ok := req.Content["displayName"]; ok {
		newContent["displayName"] = v
	}
	if v, ok := req.Content["gidNumber"]; ok {
		newContent["gidNumber"] = v
	}
	if v, ok := req.Content["givenName"]; ok {
		newContent["givenName"] = v
	}
	if v, ok := req.Content["homeDirectory"]; ok {
		newContent["homeDirectory"] = v
	}
	// Set constant objectClass array.
	newContent["objectClass"] = []string{"top", "inetOrgPerson", "posixAccount", "helxUser"}
	newContent["ou"] = "users"
	if v, ok := req.Content["sn"]; ok {
		newContent["sn"] = v
	}
	newContent["uid"] = uid
	if v, ok := req.Content["uidNumber"]; ok {
		newContent["uidNumber"] = v
	}

	// Populate the pidUidMap with pid -> uid.
	if pid, ok := req.Content["pid"].(string); ok {
		pidUidMap[pid] = uid
	}

	transformed := &Transformed{
		DN:      newDN,
		Content: newContent,
	}
	return transformed, []SearchSpec{}, false
}

// hookHandler processes POST requests to the /hook endpoint.
//
// @Summary Process LDAP hook
// @Description Receives LDAP entry payloads and returns a transformed
//              object along with derived search definitions.
// @Tags hook
// @Accept json
// @Produce json
// @Param payload body HookRequest true "LDAP Hook Request"
// @Success 200 {object} HookResponse
// @Failure 400 {object} ErrorResponse
// @Router /hook [post]
func hookHandler(c echo.Context) error {
	var req HookRequest
	if err := c.Bind(&req); err != nil {
		return c.JSON(http.StatusBadRequest,
			ErrorResponse{Message: "Invalid request payload"})
	}

	var resp HookResponse

	// Determine object type using DN and content's objectClass.
	objClass, exists := req.Content["objectClass"]
	if strings.Contains(req.DN, "ou=Groups") || (exists && contains(objClass, "UNCGroup")) {
		transformed, derived, reset := processGroup(req)
		resp.Transformed = transformed
		resp.Derived = derived
		resp.Reset = reset
	} else if strings.Contains(req.DN, "ou=people") || (exists && contains(objClass, "UNCPerson")) {
		transformed, derived, reset := processUser(req)
		resp.Transformed = transformed
		resp.Derived = derived
		resp.Reset = reset
	} else {
		log.Println("Unknown object type")
		return c.JSON(http.StatusBadRequest,
			ErrorResponse{Message: "Unknown object type"})
	}

	// Log a summary of the transformation for debugging.
	log.Printf("Transformation summary: transformed=%+v, derived=%+v, reset=%v",
		resp.Transformed, resp.Derived, resp.Reset)

	return c.JSON(http.StatusOK, resp)
}

func main() {
	e := echo.New()

	// Register the /hook endpoint.
	e.POST("/hook", hookHandler)

	// Start the server on port 5001.
	if err := e.Start(":5001"); err != nil {
		log.Fatal(err)
	}
}

package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"sync"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

// HookRequest represents the payload sent by the LDAP system.
// swagger:model HookRequest
type HookRequest struct {
	// DN is the distinguished name of the LDAP entry.
	// example: cn=unc:app:renci:ordrd-example,ou=Groups,dc=unc,dc=edu
	DN string `json:"dn"`
	// Content is a JSON object representing LDAP attributes.
	Content map[string]interface{} `json:"content"`
}

// DerivedSearch defines a search specification generated from the hook.
// swagger:model DerivedSearch
type DerivedSearch struct {
	// ID is a unique search identifier.
	// example: ordrd-members
	ID string `json:"id"`
	// Filter is an LDAP filter string.
	// example: (|(pid=713272486)(pid=709909262)(pid=730294000)(pid=700268159)(pid=730383111))
	Filter string `json:"filter"`
	// Refresh specifies the refresh interval in seconds.
	// example: 10
	Refresh int `json:"refresh"`
	// BaseDN is the base DN to use for the search.
	// example: ou=people,dc=unc,dc=edu
	BaseDN string `json:"baseDN"`
}

// TransformedEntry is the transformed LDAP entry.
type TransformedEntry struct {
	// DN is the transformed distinguished name.
	DN string `json:"dn"`
	// Content is the transformed content.
	Content map[string]interface{} `json:"content"`
}

// HookResponse is the response returned by the hook service.
// swagger:model HookResponse
type HookResponse struct {
	// Transformed holds the transformed LDAP entry. It is null if errors occur.
	Transformed *TransformedEntry `json:"transformed"`
	// Derived is an array of additional search specifications.
	Derived []DerivedSearch `json:"derived"`
	// Reset indicates whether the internal state should be reset.
	Reset bool `json:"reset"`
}

var (
	// pidUidMap maintains a mapping from pid to uid. This map is updated when
	// processing UNC User entries.
	pidUidMap      = make(map[string]string)
	pidUidMapMutex = &sync.RWMutex{}
)

func main() {
	e := echo.New()
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())

	// @title ordrd-group-x Hook Service API
	// @version 1.0.1
	// @description This service processes LDAP hook events.
	// @host localhost:5001
	// @BasePath /

	e.POST("/hook", hookHandler)
	e.Logger.Fatal(e.Start(":5001"))
}

// hookHandler processes the LDAP hook payload and returns the transformed data,
// derived search specifications, and reset directive.
// @Summary Process LDAP hook payload
// @Description Process incoming LDAP hook payloads to transform data,
// inspect object type, and generate derived search specifications.
// @Tags hook
// @Accept  json
// @Produce  json
// @Param   payload  body  HookRequest  true  "LDAP Hook Payload"
// @Success 200 {object} HookResponse
// @Failure 400 {object} map[string]string
// @Router /hook [post]
func hookHandler(c echo.Context) error {
	var req HookRequest
	if err := c.Bind(&req); err != nil {
		log.Printf("Error binding request: %v", err)
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "Invalid request"})
	}

	// Validate presence of DN and content.
	if req.DN == "" || req.Content == nil {
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "Missing dn or content"})
	}

	var response HookResponse

	// Determine object type based on DN.
	// Users may extend this logic to inspect additional fields.
	if strings.Contains(strings.ToLower(req.DN), "ou=groups") {
		// Process group entries (Example1)
		transformed, derived, reset := processGroup(req)
		response.Transformed = transformed
		response.Derived = derived
		response.Reset = reset
	} else if strings.Contains(strings.ToLower(req.DN), "ou=people") {
		// Process user entries (Example2)
		transformed, derived, reset := processUser(req)
		response.Transformed = transformed
		response.Derived = derived
		response.Reset = reset
	} else {
		// Unknown object type: user may insert custom handling logic here.
		log.Printf("Unknown object type for DN: %s", req.DN)
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "Unknown object type"})
	}

	// Output a summary for debugging purposes.
	summary, _ := json.MarshalIndent(response, "", "  ")
	log.Printf("Processing Summary:\n%s", string(summary))

	return c.JSON(http.StatusOK, response)
}

// processUser handles transformation for UNC User entries (Example2).
// It extracts the pid and uid to update the pidUidMap.
func processUser(req HookRequest) (*TransformedEntry, []DerivedSearch, bool) {
	content := req.Content

	// Extract pid and uid from content.
	pid, okPid := content["pid"].(string)
	uid, okUid := content["uid"].(string)
	if !okPid || !okUid {
		log.Printf("Missing pid or uid in user entry")
		// If required fields are missing, return null transformed and set reset.
		return nil, []DerivedSearch{}, true
	}

	// Update the global pidUidMap.
	pidUidMapMutex.Lock()
	pidUidMap[pid] = uid
	pidUidMapMutex.Unlock()

	// Build the transformed user entry.
	transformed := &TransformedEntry{
		DN: "uid=" + uid + ",ou=users,dc=example,dc=org",
		Content: map[string]interface{}{
			"cn":           content["cn"],
			"displayName":  content["displayName"],
			"gidNumber":    content["gidNumber"],
			"givenName":    content["givenName"],
			"homeDirectory": content["homeDirectory"],
			"objectClass":  []string{"top", "inetOrgPerson", "posixAccount", "helxUser"},
			"ou":           "users",
			"sn":           content["sn"],
			"uid":          uid,
			"uidNumber":    content["uidNumber"],
		},
	}

	// No derived searches are generated for user entries.
	return transformed, []DerivedSearch{}, false
}

// processGroup handles transformation for ORDRD Group entries (Example1).
// It transforms the group name, processes member entries, and generates a
// derived search specification. The user may replace the sample logic with
// their own custom transformation.
func processGroup(req HookRequest) (*TransformedEntry, []DerivedSearch, bool) {
	content := req.Content

	// Expect "member" to be an array of strings.
	members, ok := content["member"].([]interface{})
	if !ok {
		log.Printf("Missing or invalid member list in group entry")
		// If member list is missing, skip processing.
		return nil, []DerivedSearch{}, true
	}

	// Transform group name by removing a prefix (e.g., "unc:app:renci:").
	cnRaw, ok := content["cn"].(string)
	if !ok {
		cnRaw = ""
	}
	groupName := strings.Replace(cnRaw, "unc:app:renci:", "", 1)

	// Process each member to build new member list and LDAP filter parts.
	newMembers := []string{}
	filterParts := ""
	allFound := true

	for _, m := range members {
		memberStr, ok := m.(string)
		if !ok {
			continue
		}
		// Expected format: "pid=xxx,ou=people,dc=unc,dc=edu"
		parts := strings.Split(memberStr, ",")
		if len(parts) == 0 {
			continue
		}
		pidPart := parts[0] // e.g., "pid=xxx"
		pidKV := strings.SplitN(pidPart, "=", 2)
		if len(pidKV) != 2 {
			continue
		}
		pid := pidKV[1]

		// Lookup uid in the pidUidMap.
		pidUidMapMutex.RLock()
		uid, exists := pidUidMap[pid]
		pidUidMapMutex.RUnlock()
		if !exists {
			allFound = false
			log.Printf("PID %s not found in pidUidMap", pid)
		}
		// If uid is found, substitute it; otherwise, use a template placeholder.
		var memberTransformed string
		if exists {
			memberTransformed = "uid=" + uid + ",ou=users,dc=example,dc=org"
		} else {
			memberTransformed = "uid={{ pidUidMap[\"" + pid + "\"] }},ou=users,dc=example,dc=org"
		}
		newMembers = append(newMembers, memberTransformed)
		filterParts += "(pid=" + pid + ")"
	}

	// Construct a derived search if member entries exist.
	derivedSearch := []DerivedSearch{}
	if len(newMembers) > 0 {
		filter := "(|" + filterParts + ")"
		derivedSearch = append(derivedSearch, DerivedSearch{
			ID:      "ordrd-members",
			Filter:  filter,
			Refresh: 10,
			BaseDN:  "ou=people,dc=unc,dc=edu",
		})
	}

	// Build the transformed group entry.
	transformed := &TransformedEntry{
		DN: "cn=" + groupName + ",ou=groups,dc=example,dc=org",
		Content: map[string]interface{}{
			"cn":          groupName,
			"member":      newMembers,
			"objectClass": []string{"top", "groupOfNames"},
		},
	}

	// If any member's pid was not found, signal a reset.
	if !allFound {
		return nil, derivedSearch, true
	}
	return transformed, derivedSearch, false
}

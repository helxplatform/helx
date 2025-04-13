// main.go
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"strings"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

// Global mapping of pid -> uid.
// For UNC User entries, this map is populated.
var pidUidMap = make(map[string]string)

// Global baseGid variable. It can be set via a command line flag.
var baseGid string

// HookRequest represents the incoming payload for the hook.
// It contains the distinguished name and the LDAP entry attributes.
type HookRequest struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// TransformedPayload represents the transformed LDAP entry.
type TransformedPayload struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// SearchSpec describes an additional search specification.
type SearchSpec struct {
	ID      string `json:"id"`
	Filter  string `json:"filter"`
	Refresh int    `json:"refresh"`
	BaseDN  string `json:"baseDN"`
	// Oneshot is optional; it is included when applicable.
	Oneshot bool `json:"oneshot"`
}

// HookResponse is the response JSON returned by the hook service.
type HookResponse struct {
	Transformed *TransformedPayload `json:"transformed"`
	Derived     []SearchSpec        `json:"derived"`
	Reset       bool                `json:"reset"`
}

// @Summary      Hook endpoint for LDAP synchronization
// @Description  Accepts a JSON payload with DN and content, applies transformation
//
//	logic based on the object type of the LDAP entry. Returns transformed
//	output, derived search definitions and a reset flag.
//
// @Tags         hook
// @Accept       json
// @Produce      json
// @Param        payload  body      HookRequest  true  "Hook Payload"
// @Success      200      {object}  HookResponse
// @Failure      400      {object}  map[string]string
// @Router       /hook [post]
func hookHandler(c echo.Context) error {
	var req HookRequest
	if err := c.Bind(&req); err != nil {
		return c.JSON(http.StatusBadRequest,
			map[string]string{"error": "invalid request payload"})
	}

	response := HookResponse{
		Derived: []SearchSpec{},
	}

	// Based on DN and content, decide how to transform.
	// ----------------------------------------------------------------------
	// Example2: UNC User entries (dn starts with "pid=").
	if strings.HasPrefix(req.DN, "pid=") {
		// --- UNC User Transformation (Example2) ---
		//
		// Special instructions:
		// - Extract pid and uid to update the pidUidMap.
		// - Use the global baseGid for all gidNumber.
		// - Build a transformed DN and content with limited fields.
		pid, ok1 := req.Content["pid"].(string)
		uid, ok2 := req.Content["uid"].(string)
		if ok1 && ok2 {
			pidUidMap[pid] = uid
		} else {
			return c.JSON(http.StatusBadRequest,
				map[string]string{"error": "missing pid or uid in content"})
		}
		newDN := "uid=" + uid + ",ou=users,dc=example,dc=org"
		newContent := map[string]interface{}{
			"cn":            req.Content["cn"],
			"displayName":   req.Content["displayName"],
			"gidNumber":     baseGid,
			"givenName":     req.Content["givenName"],
			"homeDirectory": "/home/" + uid,
			"objectClass":   []string{"top", "inetOrgPerson", "posixAccount", "helxUser"},
			"ou":            "users",
			"sn":            req.Content["sn"],
			"uid":           uid,
			"uidNumber":     req.Content["uidNumber"],
		}

		transformed := TransformedPayload{
			DN:      newDN,
			Content: newContent,
		}
		response.Transformed = &transformed

		// Create a derived search specification.
		uidNumber := fmt.Sprintf("%v", req.Content["uidNumber"])
		derived := SearchSpec{
			ID:      uidNumber + "-posixGroups",
			Filter:  "(&(objectClass=posixGroup)(memberUid=" + uidNumber + "))",
			Refresh: 10,
			BaseDN:  "ou=Systems,ou=PosixGroups,dc=unc,dc=edu",
			Oneshot: false,
		}
		response.Derived = append(response.Derived, derived)
		response.Reset = false

		log.Printf("UNC User Transformation: %+v, Derived: %+v, Reset: %v",
			transformed, response.Derived, response.Reset)
		return c.JSON(http.StatusOK, response)
	}

	// ----------------------------------------------------------------------
	// Example1: ORDRD Group entries (DN starts with "cn=unc:app:renci:").
	if strings.HasPrefix(req.DN, "cn=unc:app:renci:") {
		// --- ORDRD Group Transformation (Example1) ---
		//
		// Special instructions:
		// - Extract groupname from the DN.
		// - Map each group member's pid using the global pidUidMap.
		// - If any mapping is missing, output transformed=null and set reset=true.
		// - Otherwise, build a new DN and transform member values.
		parts := strings.Split(req.DN, ":")
		groupPart := parts[len(parts)-1]
		groupname := strings.Split(groupPart, ",")[0]

		// Retrieve member list from content.
		membersRaw, ok := req.Content["member"]
		if !ok {
			return c.JSON(http.StatusBadRequest,
				map[string]string{"error": "member attribute missing"})
		}
		var members []string
		switch v := membersRaw.(type) {
		case []interface{}:
			for _, m := range v {
				if memberStr, ok := m.(string); ok {
					members = append(members, memberStr)
				}
			}
		case string:
			members = append(members, v)
		default:
			return c.JSON(http.StatusBadRequest,
				map[string]string{"error": "invalid member attribute type"})
		}

		// Check if all pids have mapping in pidUidMap.
		missingMapping := false
		for _, m := range members {
			if strings.HasPrefix(m, "pid=") {
				pidPart := strings.TrimPrefix(m, "pid=")
				pid := strings.Split(pidPart, ",")[0]
				if _, exists := pidUidMap[pid]; !exists {
					missingMapping = true
					break
				}
			} else {
				missingMapping = true
				break
			}
		}

		if missingMapping {
			// If any uid mapping is missing, no transformation occurs.
			response.Transformed = nil
			response.Reset = true
		} else {
			newDN := "cn=" + groupname + ",ou=groups,dc=example,dc=org"
			transformedContent := make(map[string]interface{})
			transformedContent["cn"] = groupname

			// Transform each member value.
			var newMembers []string
			for _, m := range members {
				pidPart := strings.TrimPrefix(m, "pid=")
				pid := strings.Split(pidPart, ",")[0]
				mappedUID := pidUidMap[pid]
				newMember := "uid=" + mappedUID + ",ou=users,dc=example,dc=org"
				newMembers = append(newMembers, newMember)
			}
			transformedContent["member"] = newMembers
			transformedContent["objectClass"] = []string{"top", "groupOfNames"}

			transformed := TransformedPayload{
				DN:      newDN,
				Content: transformedContent,
			}
			response.Transformed = &transformed
			response.Reset = false
		}

		// Build derived search specification using all pids.
		filter := "(|"
		for _, m := range members {
			if strings.HasPrefix(m, "pid=") {
				pidPart := strings.TrimPrefix(m, "pid=")
				pid := strings.Split(pidPart, ",")[0]
				filter += "(pid=" + pid + ")"
			}
		}
		filter += ")"
		derived := SearchSpec{
			ID:      "ordrd-members",
			Filter:  filter,
			Refresh: 10,
			BaseDN:  "ou=people,dc=unc,dc=edu",
			Oneshot: false,
		}
		response.Derived = append(response.Derived, derived)

		log.Printf("ORDRD Group Transformation: Transformed: %+v, Derived: %+v, Reset: %v",
			response.Transformed, response.Derived, response.Reset)
		return c.JSON(http.StatusOK, response)
	}

	// ----------------------------------------------------------------------
	// Example3: Posix Group entries (DN contains "ou=PosixGroups").
	if strings.Contains(req.DN, "ou=PosixGroups") {
		// --- Posix Group Transformation (Example3) ---
		//
		// Transform the DN and select only specific attributes.
		cnVal, ok := req.Content["cn"].(string)
		if !ok {
			return c.JSON(http.StatusBadRequest,
				map[string]string{"error": "cn attribute missing"})
		}
		newDN := "cn=" + cnVal + ",ou=groups,dc=example,dc=org"
		transformedContent := make(map[string]interface{})
		if v, exists := req.Content["cn"]; exists {
			transformedContent["cn"] = v
		}
		if v, exists := req.Content["description"]; exists {
			transformedContent["description"] = v
		}
		if v, exists := req.Content["gidNumber"]; exists {
			transformedContent["gidNumber"] = v
		}
		// Overwrite objectClass to only include "posixGroup".
		transformedContent["objectClass"] = []string{"posixGroup"}
		if v, exists := req.Content["memberuid"]; exists {
			transformedContent["memberuid"] = v
		}
		transformed := TransformedPayload{
			DN:      newDN,
			Content: transformedContent,
		}
		response.Transformed = &transformed
		response.Derived = []SearchSpec{}
		response.Reset = false

		log.Printf("Posix Group Transformation: %+v, Derived: %+v, Reset: %v",
			transformed, response.Derived, response.Reset)
		return c.JSON(http.StatusOK, response)
	}

	// ----------------------------------------------------------------------
	// Unknown object type.
	// Users may add additional handling here.
	log.Printf("Unknown object type with DN: %s", req.DN)
	return c.JSON(http.StatusBadRequest,
		map[string]string{"error": "unknown object type"})
}

func main() {
	// Set up flag to allow customization of the baseGid.
	flag.StringVar(&baseGid, "baseGid", "300", "Base GID for POSIX groups")
	flag.Parse()

	// Create new Echo instance.
	e := echo.New()
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())

	// Register routes.
	e.POST("/hook", hookHandler)

	// Start server on port 5001.
	addr := ":5001"
	log.Printf("Starting ordrd-group-x on %s...", addr)
	if err := e.Start(addr); err != nil {
		log.Fatal(err)
	}
}

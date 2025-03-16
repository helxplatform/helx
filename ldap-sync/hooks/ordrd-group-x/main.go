package main

import (
	"net/http"
	"strings"

	"log"

	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

// HookRequest represents the incoming payload.
// It includes a DN and a content object with LDAP attributes.
type HookRequest struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// TransformedContent holds the transformed attributes.
type TransformedContent struct {
	CN          string   `json:"cn"`
	Member      []string `json:"member"`
	ObjectClass []string `json:"objectClass"`
}

// Transformed is the transformed LDAP entry.
type Transformed struct {
	DN      string             `json:"dn"`
	Content TransformedContent `json:"content"`
}

// DerivedSpec describes the derived search specification.
type DerivedSpec struct {
	ID      string `json:"id"`
	Filter  string `json:"filter"`
	Refresh int    `json:"refresh"`
	BaseDN  string `json:"baseDN"`
}

// HookResponse is the complete response payload.
type HookResponse struct {
	Transformed Transformed   `json:"transformed"`
	Derived     []DerivedSpec `json:"derived"`
}

// @title LDAP Sync Hook Service
// @version 1.0
// @description This service transforms LDAP entries and derives additional search specifications.
// @host localhost:5001
// @BasePath /
func main() {
	e := echo.New()
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())

	// Register the /hook endpoint
	e.POST("/hook", hookHandler)

	// Start server on port 5001
	log.Fatal(e.Start(":5001"))
}

// hookHandler godoc
// @Summary Process LDAP hook payload
// @Description Receives an LDAP entry, applies transformation logic, and returns the transformed entry along with derived search specifications.
// @Accept json
// @Produce json
// @Param payload body HookRequest true "LDAP Entry Payload"
// @Success 200 {object} HookResponse
// @Failure 400 {object} map[string]string
// @Router /hook [post]
func hookHandler(c echo.Context) error {
	var req HookRequest
	if err := c.Bind(&req); err != nil {
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "invalid request payload"})
	}

	// --- Transformation logic START ---
	// Extract the component from the source cn.
	// The transformed cn is the substring after the last ':'.
	sourceCN, ok := req.Content["cn"].(string)
	if !ok || sourceCN == "" {
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "invalid or missing cn in content"})
	}
	parts := strings.Split(sourceCN, ":")
	transformedCN := parts[len(parts)-1]

	// Transform the DN.
	// Format per sample: "<transformedCN>,ou=groups,dc=example,dc=org"
	transformedDN := "cn=" + transformedCN + ",ou=groups,dc=example,dc=org"

	// Transform the member list.
	// For each member (expected in the format "pid=xxx,ou=people,dc=unc,dc=edu"),
	// change to "uid=xxx,ou=users,dc=example,dc=org".
	var transformedMembers []string
	if members, exists := req.Content["member"]; exists {
		switch v := members.(type) {
		case []interface{}:
			for _, m := range v {
				if mstr, ok := m.(string); ok {
					num := extractNumber(mstr)
					newMember := "uid=" + num + ",ou=users,dc=example,dc=org"
					transformedMembers = append(transformedMembers, newMember)
				}
			}
		case string:
			num := extractNumber(v)
			newMember := "uid=" + num + ",ou=users,dc=example,dc=org"
			transformedMembers = append(transformedMembers, newMember)
		}
	}

	// Set a constant objectClass value.
	transformedObjectClass := []string{"top", "groupOfNames"}

	transformedContent := TransformedContent{
		CN:          transformedCN,
		Member:      transformedMembers,
		ObjectClass: transformedObjectClass,
	}

	transformed := Transformed{
		DN:      transformedDN,
		Content: transformedContent,
	}

	// Build the derived search specification.
	// The filter is constructed from each transformed member.
	var filterParts []string
	for _, m := range transformedMembers {
		// Extract the UID value from the member string.
		num := extractUID(m)
		filterParts = append(filterParts, "(pid="+num+")")
	}
	// Construct the LDAP filter. Standard format: "(|(uid=...)(uid=...))"
	derivedFilter := "(|" + strings.Join(filterParts, "") + ")"

	derivedSpec := DerivedSpec{
		ID:      "ordrd-members",
		Filter:  derivedFilter,
		Refresh: 10,
		BaseDN:  "ou=people,dc=unc,dc=edu",
	}

	// --- Transformation logic END ---
	// NOTE: Replace the above transformation logic with your own code if needed.

	response := HookResponse{
		Transformed: transformed,
		Derived:     []DerivedSpec{derivedSpec},
	}

	return c.JSON(http.StatusOK, response)
}

// extractNumber extracts the number following "pid=" from a given string.
// For example, from "pid=713272486,ou=people,dc=unc,dc=edu" it returns "713272486".
func extractNumber(s string) string {
	s = strings.TrimSpace(s)
	if strings.HasPrefix(s, "pid=") {
		s = strings.TrimPrefix(s, "pid=")
	}
	if idx := strings.Index(s, ","); idx != -1 {
		return s[:idx]
	}
	return s
}

// extractUID extracts the UID from a transformed member string.
// For example, from "uid=713272486,ou=users,dc=example,dc=org" it returns "713272486".
func extractUID(s string) string {
	s = strings.TrimSpace(s)
	if strings.HasPrefix(s, "uid=") {
		s = strings.TrimPrefix(s, "uid=")
	}
	if idx := strings.Index(s, ","); idx != -1 {
		return s[:idx]
	}
	return s
}

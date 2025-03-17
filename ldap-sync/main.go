package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"

	_ "main/docs" // Replace with your actual module path.

	"github.com/go-ldap/ldap/v3"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	echoSwagger "github.com/swaggo/echo-swagger"
	"gopkg.in/yaml.v2"
)

// LDAPConfig holds connection details for one LDAP server.
type LDAPConfig struct {
	URL          string `yaml:"url"`
	BindDN       string `yaml:"bind_dn"`
	BindPassword string `yaml:"bind_password"`
	BaseDN       string `yaml:"base_dn"`
}

// Config holds the configuration for both source and target LDAP servers.
type Config struct {
	Source LDAPConfig `yaml:"source"`
	Target LDAPConfig `yaml:"target"`
	Hooks  []string   `yaml:"hooks"`
}

// SearchSpec represents a running search instance.
type SearchSpec struct {
	Filter  string
	Refresh int
	Stop    chan struct{}
	BaseDN  string // New field: the base DN to use for this search.
}

// SearchInfo represents the JSON structure for a search.
type SearchInfo struct {
	ID      string `json:"id"`
	Filter  string `json:"filter"`
	Refresh int    `json:"refresh"`
}

// DerivedSearchSpec describes a search as provided via a hook response.
type DerivedSearchSpec struct {
	ID      string `json:"id"`
	Filter  string `json:"filter"`
	Refresh int    `json:"refresh"`
	BaseDN  string `json:"baseDN"`
}

// LDAPResult holds an LDAP entry in a structured way.
type LDAPResult struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// Define two result types.
type ResultEntrySimple struct {
	DN string `json:"dn"`
}

type ResultEntryFull struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

type TransformedEntry struct {
	DN      string                 `json:"dn"`
	Content map[string]interface{} `json:"content"`
}

// HookResponse represents the hook response JSON.
type HookResponse struct {
	Transformed *TransformedEntry   `json:"transformed"`
	Derived     []DerivedSearchSpec `json:"derived"`
	Reset       bool                `json:"reset"`
}

var config Config
var searches = make(map[string]*SearchSpec)
var searchResults = make(map[string]map[string]LDAPResult)

// loadConfig reads the YAML config file
func loadConfig(path string) error {
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return err
	}
	return yaml.Unmarshal(data, &config)
}

// connectAndBindLDAP connects to the LDAP server using the source configuration and binds using the credentials.
// Returns an established connection or an error.
func connectAndBindLDAP() (*ldap.Conn, error) {
	l, err := ldap.DialURL(config.Source.URL)
	if err != nil {
		return nil, err
	}
	if err = l.Bind(config.Source.BindDN, config.Source.BindPassword); err != nil {
		l.Close()
		return nil, err
	}
	return l, nil
}

// performLDAPSearch performs an LDAP search using the provided connection, baseDN, and filter.
func performLDAPSearch(l *ldap.Conn, baseDN, filter string) (*ldap.SearchResult, error) {
	searchRequest := ldap.NewSearchRequest(
		baseDN,
		ldap.ScopeWholeSubtree,
		ldap.NeverDerefAliases,
		0,
		0,
		false,
		filter,
		[]string{"*"},
		nil,
	)
	return l.Search(searchRequest)
}

func storeDestinationLDAP(entry *TransformedEntry) error {
	// Connect to destination LDAP.
	l, err := ldap.DialURL(config.Target.URL)
	if err != nil {
		return err
	}
	defer l.Close()

	// Bind with destination credentials.
	if err = l.Bind(config.Target.BindDN, config.Target.BindPassword); err != nil {
		return err
	}

	// Check if the entry exists.
	searchRequest := ldap.NewSearchRequest(
		entry.DN,
		ldap.ScopeBaseObject,
		ldap.NeverDerefAliases,
		0,
		0,
		false,
		"(objectClass=*)",
		[]string{"dn"},
		nil,
	)
	sr, err := l.Search(searchRequest)
	if err != nil {
		// Check if the error is LDAP error code 32 ("No Such Object")
		if ldapErr, ok := err.(*ldap.Error); ok && ldapErr.ResultCode == ldap.LDAPResultNoSuchObject {
			// Treat it as if no entry was found.
			sr = &ldap.SearchResult{Entries: []*ldap.Entry{}}
		} else {
			return err
		}
	}

	// Prepare attributes conversion: each attribute becomes a slice of strings.
	attributes := make(map[string][]string)
	for attr, value := range entry.Content {
		switch v := value.(type) {
		case []interface{}:
			var vals []string
			for _, x := range v {
				vals = append(vals, fmt.Sprintf("%v", x))
			}
			attributes[attr] = vals
		default:
			attributes[attr] = []string{fmt.Sprintf("%v", v)}
		}
	}

	// If the entry doesn't exist, add it.
	if len(sr.Entries) == 0 {
		addReq := ldap.NewAddRequest(entry.DN, nil)
		for attr, values := range attributes {
			addReq.Attribute(attr, values)
		}
		// Optionally, ensure an objectClass is set.
		if _, exists := attributes["objectClass"]; !exists {
			addReq.Attribute("objectClass", []string{"top", "inetOrgPerson"})
		}
		if err = l.Add(addReq); err != nil {
			return err
		}
		log.Printf("Added entry %s to destination LDAP", entry.DN)
	} else {
		// If the entry exists, update it.
		modReq := ldap.NewModifyRequest(entry.DN, nil)
		for attr, values := range attributes {
			modReq.Replace(attr, values)
		}
		if err = l.Modify(modReq); err != nil {
			return err
		}
		log.Printf("Modified entry %s in destination LDAP", entry.DN)
	}
	return nil
}

// processHookResponse is a stub for processing the hook response.
func processHookResponse(resp interface{}) {
	// Convert resp (which might be a generic map) into our HookResponse struct.
	var hookResp HookResponse
	data, err := json.Marshal(resp)
	if err != nil {
		log.Printf("Error marshalling hook response: %v", err)
		return
	}
	if err := json.Unmarshal(data, &hookResp); err != nil {
		log.Printf("Error unmarshalling hook response: %v", err)
		return
	}

	// Process the transformed element (if present).
	if hookResp.Transformed != nil {
		log.Printf("Processing transformed hook response for DN: %s", hookResp.Transformed.DN)
		if err := storeDestinationLDAP(hookResp.Transformed); err != nil {
			log.Printf("Error storing entry in destination LDAP: %v", err)
		}
	} else {
		log.Printf("No transformed data in hook response")
	}

	// Process each derived search provided.
	for _, ds := range hookResp.Derived {
		if spec, exists := searches[ds.ID]; exists {
			// Update existing search.
			close(spec.Stop)
			stopChan := make(chan struct{})
			spec.Filter = ds.Filter
			spec.Refresh = ds.Refresh
			spec.BaseDN = ds.BaseDN
			spec.Stop = stopChan
			go ldapSearchAndSync(ds.ID, ds.Filter, ds.BaseDN, ds.Refresh, stopChan)
			log.Printf("Derived search updated: %s", ds.ID)
		} else {
			// Create a new search.
			stopChan := make(chan struct{})
			spec := &SearchSpec{
				Filter:  ds.Filter,
				Refresh: ds.Refresh,
				BaseDN:  ds.BaseDN,
				Stop:    stopChan,
			}
			searches[ds.ID] = spec
			// Initialize the structured results store for this search id.
			searchResults[ds.ID] = make(map[string]LDAPResult)
			go ldapSearchAndSync(ds.ID, ds.Filter, ds.BaseDN, ds.Refresh, stopChan)
			log.Printf("Derived search created: %s", ds.ID)
		}
	}
	// Process the reset directive.
	if hookResp.Reset {
		log.Printf("Reset directive received. Discarding internal search results.")
		// Clear all internal search results.
		for id := range searchResults {
			searchResults[id] = make(map[string]LDAPResult)
		}
	}
}

// sendHooks posts the LDAP result to each URL specified in config.Hooks.
func sendHooks(result LDAPResult) {
	payload, err := json.Marshal(result)
	if err != nil {
		log.Printf("Error marshalling hook payload for DN %s: %v", result.DN, err)
		return
	}
	for _, url := range config.Hooks {
		// Launch each hook call concurrently.
		go func(hookURL string) {
			resp, err := http.Post(hookURL, "application/json", bytes.NewBuffer(payload))
			if err != nil {
				log.Printf("Error posting to hook %s: %v", hookURL, err)
				return
			}
			defer resp.Body.Close()
			body, err := ioutil.ReadAll(resp.Body)
			if err != nil {
				log.Printf("Error reading hook response from %s: %v", hookURL, err)
				return
			}
			var hookResp struct {
				Transformed interface{} `json:"transformed"`
				Derived     interface{} `json:"derived"`
			}
			if err := json.Unmarshal(body, &hookResp); err != nil {
				log.Printf("Error unmarshalling hook response from %s: %v", hookURL, err)
				return
			}
			processHookResponse(hookResp)
		}(url)
	}
}

// processLDAPEntry processes a single LDAP entry, updating the searchResults
// for the given search id. It builds a structured attribute map, and logs whether
// the entry is new, updated, or unchanged.
func processLDAPEntry(id string, entry *ldap.Entry) {
	dn := entry.DN
	attrMap := make(map[string]interface{})
	for _, attr := range entry.Attributes {
		if len(attr.Values) == 1 {
			attrMap[attr.Name] = attr.Values[0]
		} else {
			attrMap[attr.Name] = attr.Values
		}
	}

	newResult := LDAPResult{
		DN:      dn,
		Content: attrMap,
	}

	// Update the searchResults for the given search id.
	if existing, exists := searchResults[id][dn]; !exists {
		searchResults[id][dn] = newResult
		log.Printf("New item retrieved: %s for search id: %s", dn, id)
		sendHooks(newResult)
	} else {
		if !reflect.DeepEqual(existing.Content, attrMap) {
			searchResults[id][dn] = newResult
			log.Printf("Updated item: %s for search id: %s", dn, id)
			sendHooks(newResult)
		} else {
			log.Printf("No change for: %s for search id: %s", dn, id)
		}
	}
}

// ldapSearchAndSync performs the LDAP search on the source server and synchronizes the results.
func ldapSearchAndSync(id, filter, baseDN string, refresh int, stopChan chan struct{}) {
	for {
		select {
		case <-stopChan:
			log.Printf("Search %s cancelled", id)
			return
		default:
		}

		log.Printf("Performing LDAP search with filter: %s for search id: %s using baseDN: %s", filter, id, baseDN)

		// Connect and bind using the helper.
		l, err := connectAndBindLDAP()
		if err != nil {
			log.Printf("Error connecting and binding to LDAP: %v", err)
			select {
			case <-stopChan:
				return
			case <-time.After(time.Duration(refresh) * time.Second):
			}
			continue
		}

		// Perform the LDAP search using the helper.
		sr, err := performLDAPSearch(l, baseDN, filter)
		if err != nil {
			log.Printf("Error performing search: %v", err)
			l.Close()
			select {
			case <-stopChan:
				return
			case <-time.After(time.Duration(refresh) * time.Second):
			}
			continue
		}
		l.Close()

		// Process each entry (using the helper we created earlier).
		for _, entry := range sr.Entries {
			processLDAPEntry(id, entry)
		}

		select {
		case <-stopChan:
			log.Printf("Search %s cancelled during wait", id)
			return
		case <-time.After(time.Duration(refresh) * time.Second):
		}
	}
}

// createSearchHandler godoc
// @Summary Create new search
// @Description Creates a new search with a unique id. Returns an error if the id already exists.
// @Tags search
// @Accept application/x-www-form-urlencoded
// @Produce json
// @Param id formData string true "Unique search id"
// @Param filter formData string true "LDAP search filter"
// @Param refresh formData int true "Refresh interval in seconds"
// @Param baseDN formData string false "Optional base DN for the search; defaults to global config if omitted"
// @Success 200 {string} string "Search created"
// @Failure 400 {string} string "Invalid parameters or search already exists"
// @Router /search [post]
func createSearchHandler(c echo.Context) error {
	id := c.FormValue("id")
	filter := strings.TrimSpace(c.FormValue("filter"))
	refreshStr := c.FormValue("refresh")
	baseDN := c.FormValue("baseDN")
	if baseDN == "" {
		baseDN = config.Source.BaseDN
	}
	if id == "" || filter == "" || refreshStr == "" {
		return c.String(http.StatusBadRequest, "Missing required parameters (id, filter, refresh)")
	}
	if _, exists := searches[id]; exists {
		return c.String(http.StatusBadRequest, "Search with this id already exists")
	}
	refresh, err := strconv.Atoi(refreshStr)
	if err != nil {
		return c.String(http.StatusBadRequest, "Invalid refresh parameter")
	}
	stopChan := make(chan struct{})
	spec := &SearchSpec{
		Filter:  filter,
		Refresh: refresh,
		Stop:    stopChan,
		BaseDN:  baseDN,
	}
	searches[id] = spec
	// Initialize the structured results store for this search id.
	searchResults[id] = make(map[string]LDAPResult)
	go ldapSearchAndSync(id, filter, baseDN, refresh, stopChan)
	return c.String(http.StatusOK, "Search created")
}

// getSearchHandler godoc
// @Summary Get search(s)
// @Description Retrieves a specific search by id if provided, or all searches if no id is specified.
// @Tags search
// @Accept json
// @Produce json
// @Param id query string false "Search ID"
// @Success 200 {object} SearchInfo "When id is provided" or {array} SearchInfo "When id is not provided"
// @Failure 404 {string} string "Search not found"
// @Router /search [get]
func getSearchHandler(c echo.Context) error {
	id := c.QueryParam("id")
	if id != "" {
		spec, exists := searches[id]
		if !exists {
			return c.String(http.StatusNotFound, "Search with given id not found")
		}
		result := SearchInfo{
			ID:      id,
			Filter:  spec.Filter,
			Refresh: spec.Refresh,
		}
		return c.JSON(http.StatusOK, result)
	}

	// No id provided; return all searches.
	var results []SearchInfo
	for k, spec := range searches {
		results = append(results, SearchInfo{
			ID:      k,
			Filter:  spec.Filter,
			Refresh: spec.Refresh,
		})
	}
	return c.JSON(http.StatusOK, results)
}

// updateSearchHandler godoc
// @Summary Update existing search
// @Description Updates an existing search (complete replacement) with new filter, refresh, and optionally baseDN. If baseDN is omitted, the global config's BaseDN is used.
// @Tags search
// @Accept application/x-www-form-urlencoded
// @Produce json
// @Param id path string true "Unique search id"
// @Param filter formData string true "LDAP search filter"
// @Param refresh formData int true "Refresh interval in seconds"
// @Param baseDN formData string false "Optional base DN for the search; defaults to global config if omitted"
// @Success 200 {string} string "Search updated"
// @Failure 400 {string} string "Invalid parameters or search does not exist"
// @Router /search/{id} [put]
func updateSearchHandler(c echo.Context) error {
	id := c.Param("id")
	filter := c.FormValue("filter")
	filter = strings.TrimSpace(filter) // Trim whitespace
	refreshStr := c.FormValue("refresh")
	// Get optional baseDN; default to global config if omitted.
	baseDN := c.FormValue("baseDN")
	if baseDN == "" {
		baseDN = config.Source.BaseDN
	}
	if id == "" || filter == "" || refreshStr == "" {
		return c.String(http.StatusBadRequest, "Missing required parameters (id, filter, refresh)")
	}
	spec, exists := searches[id]
	if !exists {
		return c.String(http.StatusBadRequest, "Search with this id does not exist")
	}
	refresh, err := strconv.Atoi(refreshStr)
	if err != nil {
		return c.String(http.StatusBadRequest, "Invalid refresh parameter")
	}
	// Cancel the current search.
	close(spec.Stop)
	// Create a new stop channel.
	stopChan := make(chan struct{})
	// Update the search spec.
	spec.Filter = filter
	spec.Refresh = refresh
	spec.BaseDN = baseDN
	spec.Stop = stopChan
	// Restart the search goroutine.
	go ldapSearchAndSync(id, filter, baseDN, refresh, stopChan)
	return c.String(http.StatusOK, "Search updated")
}

// deleteSearchHandler godoc
// @Summary Delete search
// @Description Deletes an existing search by its unique id.
// @Tags search
// @Produce json
// @Param id path string true "Unique search id"
// @Success 200 {string} string "Search deleted"
// @Failure 404 {string} string "Search not found"
// @Router /search/{id} [delete]
func deleteSearchHandler(c echo.Context) error {
	id := c.Param("id")
	spec, exists := searches[id]
	if !exists {
		return c.String(http.StatusNotFound, "Search not found")
	}
	// Cancel the running search.
	close(spec.Stop)
	// Remove from the map.
	delete(searches, id)
	return c.String(http.StatusOK, "Search deleted")
}

// getResultsHandler godoc
// @Summary Get search results
// @Description Retrieves all LDAP objects for a given search id.
//
//	If the optional query parameter "full" is true, returns both DN and content; otherwise, only DN is returned.
//
// @Tags results
// @Produce json
// @Param id path string true "Unique search id"
// @Param full query boolean false "Return full result (DN and content) if true, else only DN"
// @Success 200 {array} ResultEntrySimple "When full is false"
// @Success 200 {array} ResultEntryFull "When full is true"
// @Failure 404 {string} string "Search results not found"
// @Router /results/{id} [get]
func getResultsHandler(c echo.Context) error {
	id := c.Param("id")
	results, exists := searchResults[id]
	if !exists {
		return c.String(http.StatusNotFound, "Search results not found for id: "+id)
	}

	full, _ := strconv.ParseBool(c.QueryParam("full"))
	if full {
		var entries []ResultEntryFull
		for _, res := range results {
			entries = append(entries, ResultEntryFull(res))
		}
		return c.JSON(http.StatusOK, entries)
	}

	var entries []ResultEntrySimple
	for _, res := range results {
		entries = append(entries, ResultEntrySimple{
			DN: res.DN,
		})
	}
	return c.JSON(http.StatusOK, entries)
}

// healthzHandler handles the liveness probe.
// @Summary Liveness Probe
// @Description Returns OK if the application is running.
// @Tags probes
// @Produce json
// @Success 200 {object} map[string]string "status: ok"
// @Router /healthz [get]
func healthzHandler(c echo.Context) error {
	return c.JSON(http.StatusOK, map[string]string{"status": "ok"})
}

// readyzHandler handles the readiness probe.
// @Summary Readiness Probe
// @Description Returns OK if the application is ready to serve traffic.
// @Tags probes
// @Produce json
// @Success 200 {object} map[string]string "status: ready"
// @Router /readyz [get]
func readyzHandler(c echo.Context) error {
	return c.JSON(http.StatusOK, map[string]string{"status": "ready"})
}

// @title ldap-sync API
// @version 1.0
// @description API for synchronizing LDAP entries between two servers.
// @host localhost:5500
// @BasePath /
func main() {
	// Load configuration from /etc/ldap-sync/config.yaml.
	if err := loadConfig("/etc/ldap-sync/config.yaml"); err != nil {
		log.Fatalf("Error loading config: %v", err)
		os.Exit(1)
	}

	// Initialize Echo.
	e := echo.New()
	e.Use(middleware.Recover())

	// Configure Logger middleware to skip logging for /healthz and /readyz endpoints.
	e.Use(middleware.LoggerWithConfig(middleware.LoggerConfig{
		Skipper: func(c echo.Context) bool {
			path := c.Request().URL.Path
			return path == "/healthz" || path == "/readyz"
		},
	}))

	// Register endpoints.
	e.POST("/search", createSearchHandler)
	e.GET("/search", getSearchHandler)
	e.PUT("/search/:id", updateSearchHandler)
	e.DELETE("/search/:id", deleteSearchHandler)
	e.GET("/results/:id", getResultsHandler)
	e.GET("/healthz", healthzHandler)
	e.GET("/readyz", readyzHandler)

	// Redirect /swagger to /swagger/index.html
	e.GET("/swagger", func(c echo.Context) error {
		return c.Redirect(http.StatusMovedPermanently, "/swagger/index.html")
	})

	// Register the Swagger documentation endpoint.
	e.GET("/swagger/*", echoSwagger.WrapHandler)

	log.Println("Server started on :5500")
	e.Start(":5500")
}

# ordrd-group-x

This hook service integrates with an LDAP synchronization system and
transforms incoming LDAP entry payloads to a new format.

## Conversion Process Summary

The service performs a conversion that outputs a JSON object with three
keys:

- **transformed**: The payload after applying custom transformation.
  If required lookups (e.g. in the pidUidMap) fail, this field is set to
  null.
- **derived**: An array of LDAP search specifications derived from the
  input (e.g. for membership searches).
- **reset**: A boolean flag. When true, it instructs the driver to clear
  its stored state for an updated run.

## Transformation Logic

The code currently handles three object types:

1. **UNC User (Example2):**
   - Extracts `pid` and `uid` from the content and updates the internal
     pidUidMap.
   - Transforms the DN to `uid=<uid>,ou=users,dc=example,dc=org`.
   - Substitutes `gidNumber` with the flag-provided baseGid.
   - Generates a derived search for the user’s posix group.
2. **ORDRD Group (Example1):**
   - Removes the prefix `unc:app:renci:` from the group CN.
   - Converts each member entry from a PID format to a UID format using
     the pidUidMap.
   - If any member UID is not found, sets **transformed** to null and
     **reset** to true.
   - Creates a derived search combining all member PIDs.
3. **Posix Group (Example3):**
   - Retains a subset of the attributes, updates the DN to
     `cn=<cn>,ou=groups,dc=example,dc=org`, and preserves the
     `memberuid` field.
   - No derived search is created.

## Customization

- **Transformation Logic:**  
  Modify the switch sections in `main.go` where the processing for
  UNC User, ORDRD Group, and Posix Group is defined. Replace the sample
  code with your own business logic if needed.

- **Handling New Object Types:**  
  Add additional branches to the if-else chain in the handler to process
  new LDAP object types.

## Building and Running

- **Swagger Docs:**  
  Generate or update the API documentation by running:  
  `make docs`

- **Docker Build:**  
  Build the Docker image with:  
  `make build REPOSITORY=your_repo/ordrd-group-x VERSION=1.0.1`

- **Docker Push:**  
  Push the image using:  
  `make push REPOSITORY=your_repo/ordrd-group-x VERSION=1.0.1`

The service listens on port **5001**.

If you have any clarifying questions or suggestions for further
customization, feel free to modify the README and source code accordingly.

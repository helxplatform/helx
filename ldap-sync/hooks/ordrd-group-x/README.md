# ordrd-group-x Hook Service

This service is built with Go and the Echo framework to handle LDAP
entry events. It exposes a POST endpoint at `/hook` that accepts a JSON
payload with two fields: "dn" and "content".

## Transformation Overview

The service inspects the incoming payload to determine its object type.
Depending on the type, it applies a transformation and may generate derived
search definitions. The JSON response contains:

- **transformed**: The new DN and attributes after transformation.
  - For groups, the DN is modified (e.g. from
    `cn=unc:app:renci:ordrd-example,ou=Groups,dc=unc,dc=edu` to
    `cn=ordrd-example,ou=groups,dc=example,dc=org`). The member list is
    transformed by mapping each member's PID to a UID from an internal map.
- **derived**: An array of search specifications. For groups, a sample
  specification is created using the member PIDs.
- **reset**: A boolean indicating whether the transformation failed due to
  missing UID mappings. If any UID is not found, `transformed` is set to null
  and `reset` is true.

For UNC User entries, selected attributes are extracted and the global
pidUidMap is updated with the mapping from PID to UID.

## Customization Instructions

- **Transformation Logic**:  
  Locate the functions `processGroup` and `processUser` in `main.go`.
  Replace the sample transformation code with your own logic if needed.

- **Handling Different Object Types**:  
  The handler inspects the DN and the "objectClass" attribute to decide how
  to process the payload. Extend or modify the conditional logic in
  `hookHandler` to add support for additional object types.

- **PID to UID Mapping**:  
  The global map `pidUidMap` stores PID to UID mappings for group transformation.
  Adjust the data structure and error handling as required for your system.

## Debugging

The service logs a summary of the transformation for each request.
This summary includes the values of the "transformed", "derived", and
"reset" keys. Check the service logs to trace the conversion process.

## Building and Running

- **Makefile Targets**:
  - `docs`: Generates or updates Swagger docs using `swag init -g main.go`.
  - `build`: Depends on `docs` and builds the Docker image (linux/amd64).
  - `push`: Builds and pushes the Docker image. Override `REPO` and `TAG`
    as needed.

- **Dockerfile**:  
  Uses Go 1.23 in the build stage and an Ubuntu base image in the final
  container. The service listens on port 5001.

## Clarifying Questions / Suggestions

- Should additional validation be added for DN and filter formats?
- Is thread safety required for the pidUidMap in a concurrent environment?
- Should the transformation be extended to support more object types?

Please customize the transformation logic and error handling to suit your
specific LDAP synchronization requirements.


# ORDRD Group Hook Service

## Overview
This hook service is built with Go and the Echo framework. It is
designed to integrate with an existing LDAP synchronization system.
The service listens for POST requests on `/hook` and applies a
transformation to the LDAP entry payload.

## Transformation Process
The service accepts a JSON payload with two fields:

- **dn**: the LDAP distinguished name.
- **content**: a JSON object of LDAP attributes.

The service inspects the object type (via the `objectClass`
attribute) and performs the following:

- **Group Objects (UNCGroup)**:  
  - Removes the prefix `unc:app:renci:` from the `cn` field.
  - Rebuilds the DN as `cn={newCN},ou=groups,dc=example,dc=org`.
  - Transforms the `member` list by mapping each `pid` to its
    corresponding `uid`.  
  - Builds a derived search specification using the member pids.
  - If any `pid` is not found in the map, the transformation is set
    to null and the `reset` directive is set to true.

- **User Objects (UNCPerson)**:  
  - Extracts the `pid` and `uid` from the content.
  - Updates the internal pid-to-uid mapping.
  - Constructs a simplified LDAP entry with a new DN in the format
    `uid={uid},ou=users,dc=example,dc=org` and a trimmed attribute list.
  - No derived searches are generated in this case.

The response JSON includes three keys:
- **transformed**: The result of applying the transformation logic.
- **derived**: An array of additional search specifications.
- **reset**: A boolean that indicates whether internal search results
  should be discarded.

## Customization Instructions
- To modify the transformation logic, update the code in the
  `hookHandler` function in `main.go`. Look for the commented sections
  where sample logic is provided.
- Add further handling for different incoming object types by extending
  the type inspection section.
- Adjust the derived search logic by modifying how the LDAP filter and
  search objects are constructed.
- Ensure that the LDAP filter and DN formats meet your system's
  requirements.

## Suggestions and Clarifications
- Verify that the incoming JSON payload matches the expected format.
- Enhance error handling and add validation where necessary.
- Consider integrating persistent storage if the pid-to-uid mapping
  needs to survive restarts.
- Feel free to ask clarifying questions or extend the rules to better
  fit your transformation needs.

## Debugging
A processing summary is logged that includes the following fields:
- **transformed**
- **derived**
- **reset**

Use these logs to troubleshoot issues during the conversion process.

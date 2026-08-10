#!/usr/bin/env python

import uuid

def uuid_to_oid():
    """
    Generate a new UUID and convert it to an OID.

    This function generates a random UUID (Universally Unique Identifier) using 
    the `uuid4` function from the Python `uuid` module. The UUID is then 
    converted to an OID (Object Identifier) by appending the UUID's integer 
    representation to the OID prefix '2.25'.

    Returns:
        tuple: A tuple containing:
            - oid (str): The corresponding OID in dotted decimal format.
            - uid (UUID): The generated UUID.
    """

    # Generate a new UUID
    uid = uuid.uuid4()
    # Convert UUID to an integer and then to a dotted decimal OID string under 2.25
    oid = '2.25.' + str(uid.int)
    return oid, uid

# Generate OID and UUID
oid, new_uuid = uuid_to_oid()
print("Generated UUID:", new_uuid)
print("Corresponding OID:", oid)

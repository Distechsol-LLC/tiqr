# Fixtures

BioStar X response bodies **copied from the official Postman collection**
`https://docs.supremainc.com/specs/bsxapi-postman-collection.json`.
Nothing here is invented: if a response is not in the collection, it is not in the fixtures.

| File | Source in collection | HTTP |
|---|---|---|
| `login_failed.json` | Authorization → Login → «Login Failed» | 400 |
| `user_created.json` | User → Create New User → «New User» | 200 |
| `user_collection.json` | Access Group → View List of Users from an Access Group | 200 |
| `error_parse_json.json` | User → User: Bulk Update → error with >100 users | 400 |

The collection has **no** example response for `GET /api/devices`. Therefore, parsing
the device list is tested using the `{"XxxCollection": {"rows": [...]}}` structure,
which is common to all resources. The actual body will be added here after the first
run against the live server.

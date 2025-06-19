import json
from main import app

# Generate the OpenAPI schema
openapi_schema = app.openapi()

# Write the schema to a JSON file
with open("openapi.json", "w") as f:
    json.dump(openapi_schema, f, indent=2)

print("OpenAPI specification generated successfully as openapi.json") 
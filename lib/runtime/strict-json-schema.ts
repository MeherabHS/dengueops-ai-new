import "server-only";

type Schema = Record<string, unknown>;

const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

function resolveRef(root: Schema, reference: string): Schema {
  if (!reference.startsWith("#/$defs/")) throw new Error("unsupported_schema_reference");
  const name = reference.slice("#/$defs/".length);
  const defs = root.$defs;
  if (!isObject(defs) || !isObject(defs[name])) throw new Error("unknown_schema_reference");
  return defs[name] as Schema;
}

function matches(schema: Schema, value: unknown, root: Schema): boolean {
  try { validateNode(schema, value, root); return true; } catch { return false; }
}

function validateNode(schema: Schema, value: unknown, root: Schema): void {
  if (typeof schema.$ref === "string") return validateNode(resolveRef(root, schema.$ref), value, root);
  if ("const" in schema && !equal(value, schema.const)) throw new Error("schema_const_mismatch");
  if (Array.isArray(schema.enum) && !schema.enum.some(item => equal(item, value))) throw new Error("schema_enum_mismatch");
  const types = Array.isArray(schema.type) ? schema.type : schema.type === undefined ? [] : [schema.type];
  if (types.length) {
    const valid = types.some(type => type === "null" ? value === null : type === "object" ? isObject(value) : type === "array" ? Array.isArray(value) : type === "integer" ? Number.isInteger(value) : type === "number" ? typeof value === "number" && Number.isFinite(value) : typeof value === type);
    if (!valid) throw new Error("schema_type_mismatch");
  }
  if (typeof value === "string") {
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) throw new Error("schema_pattern_mismatch");
    if (typeof schema.minLength === "number" && value.length < schema.minLength) throw new Error("schema_min_length");
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) throw new Error("schema_max_length");
    if (schema.format === "uuid" && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) throw new Error("schema_uuid_format");
    if (schema.format === "date-time" && Number.isNaN(Date.parse(value))) throw new Error("schema_datetime_format");
  }
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) throw new Error("schema_minimum");
    if (typeof schema.maximum === "number" && value > schema.maximum) throw new Error("schema_maximum");
  }
  if (isObject(value)) {
    const required = Array.isArray(schema.required) ? schema.required : [];
    for (const key of required) if (typeof key === "string" && !(key in value)) throw new Error(`schema_required:${key}`);
    const properties = isObject(schema.properties) ? schema.properties : {};
    if (schema.additionalProperties === false) for (const key of Object.keys(value)) if (!(key in properties)) throw new Error(`schema_additional_property:${key}`);
    for (const [key, child] of Object.entries(properties)) if (key in value && isObject(child)) validateNode(child, value[key], root);
  }
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) throw new Error("schema_min_items");
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) throw new Error("schema_max_items");
    if (schema.uniqueItems === true && new Set(value.map(item=>JSON.stringify(item))).size !== value.length) throw new Error("schema_unique_items");
    if (isObject(schema.items)) for (const item of value) validateNode(schema.items, item, root);
  }
  if (Array.isArray(schema.allOf)) for (const child of schema.allOf) if (isObject(child)) validateNode(child, value, root);
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some(child => isObject(child) && matches(child, value, root))) throw new Error("schema_any_of");
  if (Array.isArray(schema.oneOf) && schema.oneOf.filter(child => isObject(child) && matches(child, value, root)).length !== 1) throw new Error("schema_one_of");
  if (isObject(schema.not) && matches(schema.not, value, root)) throw new Error("schema_not");
  if (isObject(schema.if) && matches(schema.if, value, root) && isObject(schema.then)) validateNode(schema.then, value, root);
}

export function validateStrictJsonSchema(schema: unknown, value: unknown): asserts value is Record<string, unknown> {
  if (!isObject(schema)) throw new Error("invalid_schema_document");
  validateNode(schema, value, schema);
}

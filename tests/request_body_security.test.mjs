import assert from "node:assert/strict";
import test from "node:test";
import * as importedBodyApi from "../lib/http/request-body.ts";

const {
  readBoundedBody,
  readBoundedFormData,
  readBoundedJson,
  RequestBodyError,
} = importedBodyApi.default || importedBodyApi;

test("bounded body reading stops chunked requests at the application limit", async () => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(40));
      controller.enqueue(new Uint8Array(40));
      controller.close();
    },
  });
  const request = new Request("http://local/upload", { method: "POST", body, duplex: "half" });
  await assert.rejects(() => readBoundedBody(request, 64), (error) => {
    assert.ok(error instanceof RequestBodyError);
    assert.equal(error.status, 413);
    return true;
  });
});

test("bounded JSON accepts a valid small body and rejects an oversized declaration", async () => {
  const parsed = await readBoundedJson(new Request("http://local/json", {
    method: "POST",
    body: JSON.stringify({ ok: true }),
  }));
  assert.deepEqual(parsed, { ok: true });
  const oversized = new Request("http://local/json", {
    method: "POST",
    headers: { "content-length": "65537" },
    body: "{}",
  });
  await assert.rejects(() => readBoundedJson(oversized), { status: 413, code: "request_body_too_large" });
});

test("bounded multipart parsing preserves valid form fields", async () => {
  const form = new FormData();
  form.set("note", "bounded");
  const request = new Request("http://local/form", { method: "POST", body: form });
  const parsed = await readBoundedFormData(request, 16 * 1024);
  assert.equal(parsed.get("note"), "bounded");
});
